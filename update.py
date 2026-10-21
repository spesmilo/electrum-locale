#!/usr/bin/env python3
import glob
import os
import re
import subprocess
import sys
import io
import time
import zipfile

# check dependencies are available
try:
    import requests
except ImportError as e:
    sys.exit(f"Error: {str(e)}. Try 'python3 -m pip install --user <module-name>' (or 'python3-requests' from Debian)")

try:
    import polib
except ImportError as e:
    sys.exit(f"Error: {str(e)}. Try 'python3 -m pip install --user <module-name>' (or 'python3-polib' from Debian)")

try:
    subprocess.check_output(["msgattrib", "--version"])
except (subprocess.CalledProcessError, OSError):
    raise Exception("missing gettext. Maybe try 'apt install gettext'")


crowdin_project_id = 20482  # for "Electrum" project on crowdin
crowdin_build_poll_interval_sec = 5
crowdin_build_timeout_sec = 10 * 60

BITCOIN_ADDRESS_REGEXP = re.compile('([13]|bc1)[a-zA-Z0-9]{30,}')
EMAIL_ADDRESS_REGEXP = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')

URL1_REGEXP = re.compile(r"\S+\.\S*\w+\S*/\S+")  # str has a "." and somewhere later has a "/" ==> URL?
assert URL1_REGEXP.search("download security update from scamwebsite.com/click-here") is not None
URL2_REGEXP = re.compile(r"http(s){0,1}://")

MIXED_LETTERS_AND_DIGITS_WORD_REGEXP = re.compile(  # try to match any cryptocurrency address
    r"(?a)"  # limit match to ascii, as CJK languages do not put whitespaces between words (would match full sentence otherwise)
    r"(?=\w{16,})"  # positive lookahead: check word length >=16
    r"("
        r"(\w*[a-zA-Z]\w*[0-9]\w*)|"  # contains a letter and then later a digit, OR
        r"(\w*[0-9]\w*[a-zA-Z]\w*)"   # contains a digit and then later a letter
    r")"
)
assert not (MIXED_LETTERS_AND_DIGITS_WORD_REGEXP.search("bip39 seeds cannot be converted to electrum seeds") is not None)
assert not (MIXED_LETTERS_AND_DIGITS_WORD_REGEXP.search("ライトニングは現在p2wpkhアドレスのHDウォレットでのみ利用可能です。") is not None)
assert MIXED_LETTERS_AND_DIGITS_WORD_REGEXP.search("ラ TB1Q9DVVAG8NS2EPXZ285FW03CR78HWEJP0Z7DFAFE") is not None
assert MIXED_LETTERS_AND_DIGITS_WORD_REGEXP.search("bitcoin:tb1q9dvvag8ns2epxz285fw03cr78hwejp0z7dfafe?amount=12345678") is not None
assert MIXED_LETTERS_AND_DIGITS_WORD_REGEXP.search("0x456d9347342B72BCf800bBf117391ac2f807c6bF") is not None  # eth
assert MIXED_LETTERS_AND_DIGITS_WORD_REGEXP.search("84EgZVjXKF4d1JkEhZSxm4LQQEx64AvqQEwkvWPtHEb5JMrB1Y86y1vCPSCiXsKzbfS9x8vCpx3gVgPaHCpobPYqQzANTnC") is not None  # xmr


def get_crowdin_api_key() -> str:
    crowdin_api_key = None
    if "crowdin_api_key" in os.environ:
        return os.environ["crowdin_api_key"]
    filename = os.path.expanduser('~/.crowdin_api_key')
    if os.path.exists(filename):
        with open(filename) as f:
            crowdin_api_key = f.read().strip()
    return crowdin_api_key


def pull_locale(path, *, crowdin_api_key=None):
    global_headers = {}
    if crowdin_api_key is None:
        crowdin_api_key = get_crowdin_api_key()
    if not crowdin_api_key:
        # Looks like crowdin does not even allow downloading without auth anymore.
        raise Exception("missing required crowdin_api_key")
    if crowdin_api_key:
        global_headers["Authorization"] = "Bearer {}".format(crowdin_api_key)

    if not os.path.exists(path):
        os.mkdir(path)
    os.chdir(path)

    # note: A crowdin build is a snapshot, translations edited after it was created are not in it.
    #       So we request a fresh build now, and wait for it to finish, instead of downloading an old one.
    print('Asking crowdin to build the translations...')
    # https://support.crowdin.com/developer/api/v2/?q=api#tag/Translations/operation/api.projects.translations.builds.post
    url = f'https://api.crowdin.com/api/v2/projects/{crowdin_project_id}/translations/builds'
    headers = {**global_headers, **{"content-type": "application/json"}}
    payload = {}  # same as electrum's contrib/locale/push_locale.py
    response = requests.request("POST", url, headers=headers, json=payload)
    response.raise_for_status()
    print("", "translations.builds.post:", "-" * 20, response.text, "-" * 20, sep="\n")
    build_id = response.json()["data"]["id"]

    print(f'Waiting for crowdin build {build_id} to finish...')
    # https://support.crowdin.com/developer/api/v2/?q=api#tag/Translations/operation/api.projects.translations.builds.get
    url = f'https://api.crowdin.com/api/v2/projects/{crowdin_project_id}/translations/builds/{build_id}'
    deadline = time.monotonic() + crowdin_build_timeout_sec
    while True:
        response = requests.request("GET", url, headers=headers)
        response.raise_for_status()
        build = response.json()["data"]
        print(f"\tstatus={build['status']}, progress={build.get('progress')}%")
        if build["status"] == "finished":
            break
        if build["status"] not in ("created", "inProgress"):
            raise Exception(f"crowdin build {build_id} did not finish: {build['status']=}")
        if time.monotonic() > deadline:
            raise Exception(f"timed out after {crowdin_build_timeout_sec}s waiting for crowdin build {build_id}")
        time.sleep(crowdin_build_poll_interval_sec)

    print('Asking crowdin to generate a URL for the build...')
    # https://support.crowdin.com/developer/api/v2/?q=api#tag/Translations/operation/api.projects.translations.builds.download.download
    url = f'https://api.crowdin.com/api/v2/projects/{crowdin_project_id}/translations/builds/{build_id}/download'
    headers = {**global_headers, **{"content-type": "application/json"}}
    response = requests.request("GET", url, headers=headers)
    response.raise_for_status()
    print("", "translations.builds.download.download:", "-" * 20, response.text, "-" * 20, sep="\n")

    build_url = response.json()["data"]["url"]

    # Download & unzip
    print('Downloading translations...')
    response = requests.request('GET', build_url, headers={})
    response.raise_for_status()
    s = response.content
    zfobj = zipfile.ZipFile(io.BytesIO(s))

    print('Unzipping translations...')
    prefix = "electrum-client/locale/"
    for name in zfobj.namelist():
        if not name.startswith(prefix) or name == prefix:
            continue
        if name.endswith('/'):
            if not os.path.exists(name[len(prefix):]):
                os.mkdir(name[len(prefix):])
        else:
            name_suffix = name[len(prefix):]
            with open(name_suffix, 'wb') as output:
                output.write(zfobj.read(name))
            if name.endswith('.po'):
                filter_exclude_comment_lines(name_suffix)
                filter_exclude_untranslated_strings(name_suffix)
            else:
                raise Exception(f"unexpected file inside zipfile from crowdin: {name}")


def filter_exclude_comment_lines(fname: str):
    """Remove lines starting with "#". ==> easier to review diffs

    As auto-generated comments contain line numbers, removing them makes
    reviewing diffs much more practical.

    note: we could be more relaxed and only rm lines starting with "#:",
          see https://www.gnu.org/software/gettext/manual/html_node/PO-File-Entries.html
    """
    os.rename(fname, f"{fname}.orig")
    with open(f"{fname}.orig", "r+", encoding="utf-8") as f_orig:
        with open(fname, "w", encoding="utf-8") as f_filtered:
            for line in f_orig:
                if not line.startswith("#"):
                    f_filtered.write(line)
    os.remove(f"{fname}.orig")


def filter_exclude_untranslated_strings(fname: str):
    """Remove strings with empty translations. ==> easier to review diffs"""
    cmd = ["msgattrib", "--translated", "--no-wrap", "--output-file", fname, fname]
    subprocess.check_output(cmd)


def detect_malicious_stuff_in_dir(path_locale: str) -> None:
    is_detected = False
    # scan each .po file separately
    files_list = glob.glob(f"{path_locale}/**/*.po", recursive=True)
    for fname in files_list:
        is_detected |= detect_malicious_stuff_in_po_file(fname)
    # after finding all errors, exit now if there were any:
    if is_detected:
        raise Exception("detected some possibly malicious translations. see logs above.")


def detect_malicious_stuff_in_po_file(fname: str) -> bool:
    pofile = polib.pofile(fname)

    is_detected = False
    regexes = {
        "BITCOIN_ADDRESS_REGEXP": BITCOIN_ADDRESS_REGEXP,
        "EMAIL_ADDRESS_REGEXP": EMAIL_ADDRESS_REGEXP,
        "URL1_REGEXP": URL1_REGEXP,
        "URL2_REGEXP": URL2_REGEXP,
        "MIXED_LETTERS_AND_DIGITS_WORD_REGEXP": MIXED_LETTERS_AND_DIGITS_WORD_REGEXP,
    }
    for entry in pofile:
        for regex_name, regex in regexes.items():
            if regex.search(entry.msgstr) is not None:
                print(
                    f">> regex {regex_name} matched in {fname!r},\n"
                    f"\t{entry.msgid=!r}\n"
                    f"\t{entry.msgstr=!r}\n")
                is_detected = True

    return is_detected


if __name__ == '__main__':
    path_here = os.path.dirname(os.path.realpath(__file__))
    path_locale = os.path.join(path_here, "locale")

    pull_locale(path_locale)
    detect_malicious_stuff_in_dir(path_locale)

    print('Local updates done.')
    print("Please don't commit directly to master, switch to a branch instead.")
    c = input("Do you want to git commit this? (y/n): ")
    if c != "y":
        sys.exit(0)

    print('Preparing git commit...')
    os.chdir(path_here)
    for lang in os.listdir('locale'):
        po = 'locale/%s/electrum.po' % lang
        cmd = "git add %s"%po
        os.system(cmd)

    os.system("git commit -a -m 'update translations'")
    print("please push to a branch, and open a pull request")

#!/usr/bin/env python3
import datetime
import os
import sys
import io
import zipfile


try:
    import requests
except ImportError as e:
    sys.exit(f"Error: {str(e)}. Try 'python3 -m pip install --user <module-name>'")


crowdin_project_id = 20482  # for "Electrum" project on crowdin


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

    # note: We won't request a build now, instead we download the latest build.
    #       This assumes that the push_locale script was run recently (in the past few days).
    print('Getting list of builds from crowdin...')
    # https://support.crowdin.com/developer/api/v2/?q=api#tag/Translations/operation/api.projects.translations.builds.getMany
    url = f'https://api.crowdin.com/api/v2/projects/{crowdin_project_id}/translations/builds'
    headers = {**global_headers, **{"content-type": "application/json"}}
    response = requests.request("GET", url, headers=headers)
    response.raise_for_status()
    print("", "translations.builds.getMany:", "-" * 20, response.text, "-" * 20, sep="\n")

    latest_build = response.json()["data"][0]["data"]
    assert latest_build["status"] == "finished", latest_build["status"]
    created_at = datetime.datetime.fromisoformat(latest_build["createdAt"])
    if (datetime.datetime.now(datetime.timezone.utc) - created_at) > datetime.timedelta(days=2):
        raise Exception(f"latest translation build looks too old. {created_at.isoformat()=}")
    build_id = latest_build["id"]

    print('Asking crowdin to generate a URL for the latest build...')
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
            with open(name[len(prefix):], 'wb') as output:
                output.write(zfobj.read(name))


if __name__ == '__main__':
    path_here = os.path.dirname(os.path.realpath(__file__))
    path_locale = os.path.join(path_here, "locale")
    pull_locale(path_locale)

    print('Local updates done.')
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
    print("please push")

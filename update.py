#!/usr/bin/env python3
import os
import sys
import io
import zipfile


try:
    import requests
except ImportError as e:
    sys.exit(f"Error: {str(e)}. Try 'python3 -m pip install --user <module-name>'")


def pull_locale(path):
    if not os.path.exists(path):
        os.mkdir(path)
    os.chdir(path)

    # Download & unzip
    print('Downloading translations...')
    s = requests.request('GET', 'https://crowdin.com/backend/download/project/electrum.zip').content
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

    print('Preparing git commit...')
    os.chdir(path_here)
    for lang in os.listdir('locale'):
        po = 'locale/%s/electrum.po' % lang
        cmd = "git add %s"%po
        os.system(cmd)

    os.system("git commit -a -m 'update translations'")
    print("please push")

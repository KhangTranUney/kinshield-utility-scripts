# Firebase Remote Config publisher

`config-kinshield-nonprod.yml` is a small manifest: each key becomes a Firebase
Remote Config parameter. Entries with `deleted: true` remove that parameter
from the live template. Existing parameters and conditions not named in the
manifest are preserved.

Install the Python dependencies used by the repository if they are not already
available:

```sh
python3 -m pip install PyYAML google-auth requests
```

Create a Firebase service-account key as described in
[`credentials/README.md`](credentials/README.md), then validate the merge:

```sh
python3 publish_remote_config.py --project-id YOUR_FIREBASE_PROJECT_ID
```

Publish only after validation succeeds:

```sh
python3 publish_remote_config.py --project-id YOUR_FIREBASE_PROJECT_ID --apply
```

The script reads the current template and publishes with its ETag, so it does
not overwrite concurrent Firebase Console edits. A conflict exits without
publishing; run the command again to merge against the latest template.

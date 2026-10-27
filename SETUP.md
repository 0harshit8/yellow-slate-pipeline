# Setup guide: writing Yellow Slate blogs on your laptop

This folder writes "Schools in [City]" blogs for Yellow Slate. You talk to Claude in chat,
and it does the research, the writing and the checks. You choose the schools and approve each blog.

You have **250 keywords**. They are the rows with **Sister** in the Writer column of the sheet.
The folder is already set up so it only ever touches your 250. Harshit writes the rest.

Setup takes about 30 minutes, once.

---

## What you need before you start

- A Windows laptop with internet.
- A **Claude Pro** account to log in with. The blog writing runs on it. Get the login from Harshit.
- This folder, unzipped (step 4).

---

## Step 1. Install Python

1. Go to <https://www.python.org/downloads/> and download the latest Python for Windows.
2. Run the installer. **On the first screen, tick "Add python.exe to PATH".** Then click Install Now.
3. Check it worked: open **PowerShell** (Start menu, type "PowerShell") and run:

   ```
   python --version
   ```

   You should see `Python 3.12` or newer.

## Step 2. Install Git for Windows

Claude Code needs it on Windows.

1. Download from <https://git-scm.com/downloads/win> and run the installer.
2. Click Next on every screen. The defaults are fine.

## Step 3. Install Claude Code and log in

1. In PowerShell, run:

   ```
   irm https://claude.ai/install.ps1 | iex
   ```

2. **Close PowerShell and open a new one.**
3. Run `claude`. It opens a browser to log in. Log in with the **Claude Pro** account.
4. When it says you are logged in, type `/exit` to close it.

## Step 4. Unzip the folder

1. Unzip `yellow-slate-pipeline.zip` to **`C:\yellow-slate-pipeline`**.
2. **Do not put it in OneDrive, Google Drive, or a Desktop that syncs.** Syncing breaks files
   halfway through a run.
3. Check the folder has `pipeline.py`, `.env` and `gcp-sheets-key.json` directly inside it.
   (`.env` may be hidden. In File Explorer: View > Show > Hidden items.)

## Step 5. Install the pipeline's packages

In PowerShell:

```
cd C:\yellow-slate-pipeline
python -m pip install -r requirements.txt
```

It takes a few minutes.

## Step 6. Check everything works

Still in `C:\yellow-slate-pipeline`, run these two:

```
python -m pytest -q
```

You should see `passed` at the end and no `failed`.

```
python pipeline.py status
```

The first line must say **`Only Sister's keywords (WRITER in .env)`**, and `new` should show **250**
(less once you have started). If you see that, you are ready.

---

## How to write blogs

1. Open PowerShell and run:

   ```
   cd C:\yellow-slate-pipeline
   claude
   ```

2. Talk to it in plain words. For example:
   - "what's pending"
   - "start the next 3 blogs"
3. Claude finds schools for each keyword and shows you a numbered list. It asks for the
   **search volume** of each school. Get these the way Harshit showed you, then paste a
   screenshot or type them like `1: 320, 2: 90`.
4. It suggests 8 to 12 schools. Say "ok", or change it ("drop 4, add 12").
5. It then writes the blogs on its own. **About 10 to 15 minutes per blog.** Keep the laptop on
   and awake, and keep PowerShell open.
6. It sends you a **blog.docx** preview of each one and asks: draft it, or change it?
   - Want changes: tell it what to change.
   - Happy: say "draft it". It puts the blog in Yellow Slate's system as an **unpublished draft**
     and gives you a link.
7. Send Harshit the draft link. **Never publish anything yourself.**

Work in small batches (3 to 5 blogs). The Claude Pro account has a weekly usage limit. When
Claude says the limit is reached, stop and tell Harshit.

---

## Rules

- **Never change the Writer column in the sheet.** It decides who writes which keyword.
- **Never edit `.env` or `gcp-sheets-key.json`.**
- **Keep this folder private.** It holds passwords to Yellow Slate's website and to the
  Google sheet. Don't upload it, send it on, or put it in a shared drive.
- Run it from **one laptop only**. Each blog's files stay in the `output` folder on the laptop
  that started it, so finish every blog on the same machine.
- If something shows an error, take a screenshot and send it to Harshit. Don't try other things
  on the Yellow Slate website.

## When Harshit sends an update

He will send new files. Copy them into `C:\yellow-slate-pipeline` and replace the old ones.
**Never replace `.env`, `gcp-sheets-key.json`, or the `output` folder.**

## Common problems

| You see | Do this |
|---|---|
| `python is not recognized` | Python was installed without "Add to PATH". Run the installer again, choose Modify, and tick it. |
| `claude is not recognized` | Close PowerShell and open a new one. Still failing: redo step 3. |
| `Service account key not found` | `gcp-sheets-key.json` is missing from `C:\yellow-slate-pipeline`. Ask Harshit. |
| `status` does not say "Only Sister's keywords" | Stop. Don't run anything. Tell Harshit. |
| A keyword "does nothing" | It belongs to Harshit. Only use keywords from your own list. |
| Claude says the usage limit is reached | Stop for now. Tell Harshit. |

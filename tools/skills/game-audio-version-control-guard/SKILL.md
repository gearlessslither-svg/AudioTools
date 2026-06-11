---
name: game-audio-version-control-guard
description: Guide safe source-control workflows for Unity and Wwise audio projects, including Perforce get latest, reconcile, resolve, revert, meta files, plugin binaries, SoundBanks, and generated/cache files.
---

# Game Audio Version-Control Guard

Use this skill when discussing P4/Git/source-control behavior for Unity/Wwise audio assets, especially Get Latest, Reconcile, Resolve, Revert, submit lists, `.meta` files, plugin binaries, SoundBanks, and generated output.

## Core Rules

- Close Unity, Wwise, IDEs, and tools that may lock files before large Get Latest, Revert, Resolve, Force Sync, or submit preparation.
- Unity assets under `Assets` usually require their `.meta` files to be versioned as a pair.
- Do not mix asset from one resolve side and `.meta` from another unless the GUID/reference impact is understood.
- Treat Wwise `.wwu`, `.wproj`, and source audio under project policy as authored assets.
- Treat `.cache`, profiling sessions, and temporary generated files as non-source unless the project explicitly versions them.
- SoundBanks and Wwise plugin binaries may be source-controlled by project policy; verify before deleting or submitting.
- If a depot already has a file, do not submit it as add; revert and sync/force-sync to the depot revision.

## Perforce Resolve Vocabulary

- `Accept Source`: use depot/source side to replace local target.
- `Accept Target`: keep local target.
- `Run Merge Tool`: manually merge text files when both sides have valid changes.
- For binary files, choose the winning side deliberately; there is no safe text merge.

## Investigation Workflow

1. Identify whether the file is source asset, generated output, plugin binary, SoundBank, cache, or diagnostic data.
2. Check whether the depot already tracks it.
3. Check whether local tools are open and may lock or regenerate it.
4. Determine if Reconcile shows add, edit, delete, or move.
5. For Unity assets, inspect the asset/meta pair together.
6. Recommend Revert, Get Latest, Force Sync, Resolve, or Submit based on ownership and intent.

## Common Patterns

- **Get Latest fails with rename/exists/locked file**: close Unity/Wwise/IDE, revert accidental opens, then force sync the affected files if needed.
- **Deleted then synced, but Reconcile shows changes again**: Unity/Wwise likely regenerated or modified files after opening the project.
- **New `.meta` appears**: submit it only if the corresponding asset is intended to be versioned and the depot does not already have a correct meta.
- **Wwise upgrade adds plugin files**: verify integration version and project policy; submit authored/runtime files and required metas, exclude cache/temporary output.

## Output

For source-control questions, answer with:

- **What likely happened**
- **Which side is local/depot/source/target**
- **Safe action**
- **What to close first**
- **Which files must stay paired**
- **What not to submit**

## Rules

- Do not tell the user to delete versioned files as a first step unless the purpose is force-sync recovery and tools are closed.
- Do not recommend bypassing licenses or source-control policy.
- If uncertain whether a generated artifact is versioned by policy, say so and ask or propose a non-destructive check.

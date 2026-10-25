---
name: mac-bringup
description: Use when a teammate on a Mac has pulled the UWB/beacons PR (branch uwb-leo) and wants it built, tested and fixed. The Swift code was written on Windows and never compiled, so this orchestrates scripts/mac_check.sh, parallel implementer subagents per Swift folder, a review, and the human hardware gates.
---

# mac-bringup

Playbook for Claude Code on a Mac. The Swift (contracts/swift, mac/, ios/EarmarkUWB, locator/ios) has never been compiled. You run one script, fix what breaks, then hand over to the person for the on-device gates.

Rate limits: use `model: sonnet` for implementers, `haiku` for pure log triage, never more than 3 subagents at once. Reuse the existing agents (`implementer`, `reviewer`), do not create new agent types.

## Phase 0: you (main agent), no subagents
1. Preflight: `xcodebuild -version && swift --version && xcodegen --version && uv --version && node --version`. Missing tools: `brew install xcodegen uv node`; Xcode from the App Store, then `sudo xcode-select -s /Applications/Xcode.app`, open it once, accept the license.
2. `git fetch && git switch uwb-leo && git pull`
3. `scripts/mac_check.sh` (steps: preflight, contracts-swift, mac, ios-uwb, locator, python-web; use `--only <step>` / `--skip <step>`). Logs: `logs/mac_check/<step>.log`.
4. Read the failing logs (`grep -n "error:" logs/mac_check/*.log | head -50`). Fix **contracts/swift first, alone**: the Mac app, the iOS app and their tests all depend on it. Rerun `scripts/mac_check.sh --only contracts-swift` until green. Python/web failures: fix yourself, they are small.

## Phase 1: parallel fixes (one message, up to 3 Agent calls)
Spawn in a SINGLE message, each `subagent_type: implementer`, `model: sonnet`, `isolation: worktree`, one owned folder each:
- A: `mac/` (step `mac`)
- B: `ios/EarmarkUWB/` (step `ios-uwb`; edit `project.yml`, never hand-edit the generated `.xcodeproj`)
- C: `locator/ios/` (step `locator`; spawn only if that step failed)

Prompt for each: "Own only <folder>. Loop: run `scripts/mac_check.sh --only <step>`, read `logs/mac_check/<step>.log`, fix the first errors, rerun, until green or blocked. Never edit contracts/ or config/ (if a contract change is needed, stop and propose it). Do not commit. Return a short report: fixed, remaining, uncertain."
Use a `haiku` subagent only if a log is huge and you just need the error list.

## Phase 2: merge and review
1. Merge each worktree branch back into `uwb-leo` (`git merge --no-ff <worktree-branch>`); resolve conflicts yourself.
2. `scripts/mac_check.sh` (full) until every step is PASS. A step failing only on a missing simulator or signing is an environment issue, say so instead of editing code.
3. Spawn one `reviewer` subagent (`model: sonnet`) on `git diff origin/uwb-leo...HEAD`, asking for P0/P1 findings only. Fix the P0s, rerun the full script.

## Phase 3: human gates (STOP and wait)
Print this checklist for the person and wait for them to report results. Do not continue on your own.
- [ ] Set `DEVELOPMENT_TEAM` in `ios/EarmarkUWB/project.yml` (then `xcodegen generate`) or pick the team in Xcode; change the bundle id if taken.
- [ ] Install EarmarkUWB on 4 iPhones (11 or later, not SE): 3 anchors `uwb_1..uwb_3` + 1 wearer, on a private network (hotspot or travel router). See `ios/README.md` "Mac build checklist".
- [ ] Start the live stack as in `services/hub/README.md` and `docs/project/UWB-PRD.md` (`make demo-live`; hub bus on `0.0.0.0`, `EARMARK_BUS_SECRET` set).
- [ ] Ranging gate: tape at 0.5 / 1 / 2 / 3 m, each reading within +/-0.10 m.
- [ ] Tap gate: mark 4 taped spots by knocking the wearer phone on each; every one saved within 10 cm (check in the hub log or dashboard).
- [ ] Walk gate: eyes closed, with a spotter, say "find my keys" and walk to a marked item.
- [ ] Beacon mode: a short check that main's locator path still works (`locator/docs/BRINGUP.md`).

## Phase 4: ship (only after the person reports)
1. `git add -A && git commit` with clear messages (one per concern: contracts fixes, mac, ios, locator). Never force-push.
2. `git push origin uwb-leo`
3. Post the final table: `scripts/mac_check.sh 2>&1 | tail -9 > /tmp/mac_check_table.txt; gh pr comment --body-file /tmp/mac_check_table.txt` (add the gate results the person gave you).
4. Only if every step PASSED and every gate passed: `gh pr ready`. Otherwise leave the PR as draft and list what is open.

# Raw HELLO captures

Every `HELLO_REQ` this tooling reads is written here as the bytes that actually arrived
(`*.bin`) plus a parsed sidecar (`*.json`). Written by `tablet.py` from `catch`, `bump`
and `edl-hello`.

## Why this folder exists

`docs/97` records the one structural weakness of this project's evidence: the founding
measurement - `HELLO ver=3 mode=0` from PBL - **has no raw capture anywhere in the
repository**. It is described in prose across many documents and corroborated by later
measurements, but nobody can re-read the bytes. Everything downstream inherits that
weakness: a claim about the handshake that cannot be checked against a packet.

This folder is the fix, made mechanical instead of aspirational. A future run does not
have to remember to save the packet; the tool saves it.

## Rules

- **Only real captures.** `tablet.py` refuses any source name beginning with `unit` or
  `test`. A synthetic file once landed here during development, and a folder called
  "captures" that can contain fabricated bytes is worse than no folder: it launders
  invention into evidence.
- **One pair per read.** The `.bin` is the packet exactly as received. The `.json` is
  derived and labelled as such - if they disagree, the `.bin` wins.
- **`is_goal_state` is not a claim, it is a comparison.** It is `true` only when the
  parsed `version == 3` and `mode == 0`, i.e. when the bytes say so.

## What a goal-state capture would prove

A `.bin` here with `cmd=1`, `version=3`, `mode=0` would be the first re-checkable proof
of the state this whole project is aiming for. It would not by itself prove the session
was usable - that needs the following upload to complete - but it would anchor the claim
that the state is reachable, which is currently the weakest link in the record.

# Making a release

A release is one build of the list that is published on Zenodo, given a DOI,
and from then on never changed. Somebody who cites 1.2.0 can always download
exactly the flows and factors they used. Somebody who loaded 1.1.0 into their
database is given a file that moves it to 1.2.0.

This page goes through a release from start to finish. Each step uses 1.2.0
as its example, released on 25 November 2026:

| Time (UTC) | Step | |
|---|---|---|
| 16:22 | The version and the notes are merged | [#485](https://github.com/brightway-labs/brightway-flows/pull/485) |
| 17:18 – 17:43 | Its merge commit, `5fa078b`, is tagged `1.2.0` and built from six lists | run `20261125T1721007573540000` |
| 17:46 | Factors added, snapshot recorded | |
| 17:48 | Migration from 1.1.0 written and checked | `1.1.0__1.2.0.zip` |
| 18:05 | Uploaded and published on Zenodo | [10.5281/zenodo.24540007](https://doi.org/10.5281/zenodo.24540007) |
| 18:07 | The migration counts and the DOI are added to the notes | [#486](https://github.com/brightway-labs/brightway-flows/pull/486) |

Most of that time is the build. The rest takes minutes, if nothing is
refused.

## What a release consists of

When it is finished, release 1.2.0 is:

- **a git tag**, `1.2.0`, on the commit it was built from. Anyone can check
  out that commit and see the code and the curated files that made it;
- **a section in [What changed in each release](../using/releases.md)**,
  saying what moved since 1.1.0 and why;
- **a version of the Zenodo record**, with six files:

  | File | What it is |
  |---|---|
  | `harmonised-flows-simple.json.gz` | the flows |
  | `lcia-factors.json.gz` | the factors |
  | `lcia-differences.json` | where implementations of a method disagree |
  | `consensus-flows.sqlite3` | the whole build, 2.6 GB |
  | `release-snapshot.json.gz` | what this release published, for the next release's migration to start from |
  | `1.1.0__1.2.0.zip` | the migration from the release before |

- **the website**, which serves this release and names it in every citation.

## Before you start

- **Every pull request meant for the release is merged into `main`.** The
  release is built from `main` and nothing else.
- **You can write to the Zenodo record.** You need a personal access token
  of the account that owns the
  [record](https://doi.org/10.5281/zenodo.22857949). Make one under
  Applications in the account's settings, with the `deposit:write` and
  `deposit:actions` scopes. Keep it in the environment, never in the
  repository.
- **You have the previous release's snapshot.** Snapshots are kept in a
  folder of their own, outside every data directory. For 1.2.0 that was
  `~/brightway-flows-releases/`, which held `1.0.0.json.gz` and
  `1.1.0.json.gz`. A data directory is rebuilt and deleted. A snapshot
  cannot be made again once the source files have been fetched again.
- **The source lists are the same as the last release's, or you know why
  not.** A migration expects both releases to have merged the same lists,
  and refuses otherwise (step 4). 1.2.0 added ecoinvent 3.13 to 1.1.0's
  five, which is a deliberate change. Dropping a list needs more thought:
  every row of that list is then left for a person to answer, not deleted.
- **Nobody else will build in the shared data directory until you have
  uploaded.** The release is a build of `main`, so it is built in the shared
  data directory. A `tools/refresh_base_build.py --build` started by someone
  else would overwrite it. `release-upload` would then refuse, because its
  files came from two builds.

## 1. Set the version and write the notes

On a branch:

1. Set `version` in `pyproject.toml` to the release, and run `uv lock`.
2. Add a section for it at the top of
   [What changed in each release](../using/releases.md). The heading gives
   the version and the day you will publish: `## 1.2.0 — 2026-11-25`.

The upload reads this section, so two parts of it matter more than the rest:

- **The date in the heading becomes the publication date on Zenodo.** If you
  publish on another day, change the heading, or pass `--publication-date`
  when you upload.
- **The first paragraph becomes the description of the Zenodo version.**
  Make it say what the release was built from. For 1.2.0: *Built from six
  lists: ecoinvent 3.13 joins ecoinvent 3.12, ecoinvent 3.8, BAFU 2026 v1,
  Stepwise 2006 1.09 and AGRIBALYSE 3.2, the five that 1.1.0 was built
  from.*

Go through every pull request merged since the previous tag:

```bash
git log --oneline 1.1.0..main
```

Group what a user would notice under headings, as earlier sections do. Every
count comes from the pull request it cites, and that pull request names the
build it was measured on.

Two things cannot be written yet, because the release build does not exist:
the table of what the migration holds, and the Zenodo link. Both are added in
step 7.

Merge the pull request. Its merge commit is the release.

## 2. Tag and build

Start from a clean checkout of `main` at that commit:

```bash
git checkout main && git pull
git status --short                  # must print nothing
git tag 1.2.0                       # do not push it yet
```

`git status` printing nothing matters. A build records whether its tree had
uncommitted changes, and the snapshot of such a build is refused. An
untracked folder counts too, such as a second data directory created inside
the repository.

Fetch every list the build will merge, and the factors of each list that
publishes any. The lists with factors are the ones whose manifest has an
`lcia` section:

```bash
grep -l '"lcia"' src/brightway_flows/data/sources/*.json
```

Then build. The order of the `--source` options is the order the lists are
merged, and it must be the same as the previous release's, apart from a list
being added or dropped. This is the build of 1.2.0:

```bash
uv run brightway-flows build \
    --source ecoinvent-3.13 --source ecoinvent-3.12 --source ecoinvent-3.8 \
    --source bafu-2026-v1 --source stepwise-2006-1.09 --source agribalyse-3.2
uv run brightway-flows characterise
```

The build took 25 minutes and `characterise` one more. If `characterise`
stops on a missing factor file, run `fetch-lcia` for that list and run
`characterise` again. The build does not need to be repeated.

**Check the build before you go further.** Run
`uv run brightway-flows assess`. Under *Since the baseline* it lists every
measure that has moved since the baseline was last recorded, and labels
each one improved or regressed. Each movement should be one that a merged
pull request explains. A regression that is released stays in that release
for good. See [Assessing a build](assessing.md).

## 3. Record the snapshot

```bash
uv run brightway-flows release-snapshot
```

It reads the tag on the build's commit and writes
`releases/1.2.0.json.gz` in the data directory. If it refuses with a message
about an untagged commit or a modified tree, go back to step 2: the tag is
missing, or `git status` was not empty when you built.

Copy the snapshot into the release folder at once, and make it read-only:

```bash
cp ~/.local/share/brightway-flows/releases/1.2.0.json.gz ~/brightway-flows-releases/
chmod a-w ~/brightway-flows-releases/1.2.0.json.gz
```

The next release's migration starts from this copy.

## 4. Write the migration from the previous release

```bash
uv run brightway-flows release-migrations \
    --from ~/brightway-flows-releases/1.1.0.json.gz --to 1.2.0 \
    --allow-different-sources
```

`--allow-different-sources` is there because 1.2.0 merged ecoinvent 3.13
and 1.1.0 did not. Without it the command refuses and names the lists that
differ. Leave it out when both releases merged the same lists, so that a
list dropped by mistake is caught.

It writes the substances, flows, impact categories and factors that changed.
It then checks them, the way a user would apply them: it applies the
migration to 1.1.0 and compares the result with 1.2.0, table by table. Only
when every table matches does it write
`releases/migrations/1.1.0__1.2.0.zip`.

Two things can stop it:

- **It exits with status 3 and names rows.** Applying the files did not give
  1.2.0. That is a defect in the migration code, not in either release. Open
  an issue and do not upload.
- **`unresolved.json` is not empty.** These are changes a program should not
  decide: a flow split in two, a unit that changed, an impact category that
  is gone. Answer each in `release-migration-rulings.json`, naming the two
  releases, the entity and the identifier, and run the command again. 1.2.0
  had none to answer.

Copy the zip into the release folder too:

```bash
cp -r ~/.local/share/brightway-flows/releases/migrations/1.1.0__1.2.0* \
    ~/brightway-flows-releases/migrations/
```

Write down what the migration holds: how many substances, flows, impact
categories and factors it creates, updates, replaces and deletes, and how
many are left for a person. Step 7 puts that table in the notes.

## 5. Upload to Zenodo

```bash
export ZENODO_ACCESS_TOKEN=...
uv run brightway-flows release-upload --version 1.2.0
```

It adds a new version to the record, uploads the six files, and sets the
version's title, date and description from the notes.

**It checks everything before it changes anything on Zenodo.** It refuses:

- a file that is missing;
- files that more than one build wrote, which is what happens if somebody
  built in the data directory after you did;
- a snapshot of an untagged commit, or of a tree with uncommitted changes;
- notes with no section for this version;
- a migration that starts from any release other than the latest one on
  Zenodo.

**The upload is left as a draft.** It prints the draft's address. Open it,
and check the title, the date, the description and the six files. Then
press Publish. A published version keeps its DOI and its files for good;
if something is wrong after that, the only fix is another release.
`--publish` publishes in the same step, without the check by eye.

If the upload is interrupted, run the command again. Files already on the
draft are replaced.

The command ends by writing `release.draft.json` in the data directory. Once
you have published the draft, rename it to `release.json`. It holds the
version, the DOI, the date, and the size and SHA-256 checksum of each
uploaded file. The website reads it in step 8.

**To rehearse first**, make a record and a token on
<https://sandbox.zenodo.org> and add
`--sandbox --concept-record <that record's number>`. Nothing on the real
record is touched, and no release file is written.

## 6. Push the tag

```bash
git push origin 1.2.0
```

Push it only now. Until the version is published, a mistake in steps 2 to 5
can still be fixed by deleting the local tag and starting again. Once the
tag is pushed, other people have it.

## 7. Finish the notes

On a branch, as in [#486](https://github.com/brightway-labs/brightway-flows/pull/486):

- Add `Published on [Zenodo](https://doi.org/…)` to the release's section,
  with the version's own DOI, not the record's.
- Add a section `### The migration from 1.1.0` with the table from step 4,
  and name the build it came from: the tag, the commit and the run.
- Change the DOI badge at the top of `README.md` to the new version.

Merge it.

## 8. Point the website at the release

The website serves the release its `release.json` names, and downloads that
release's database from Zenodo. Nothing has to be copied from the build.

Put the `release.json` from step 5 in the web server's data directory, or
wherever `BRIGHTWAY_FLOWS_RELEASE_FILE` points, and on the server:

```bash
uv run --no-sync brightway-flows release-download   # the database, 2.6 GB
sudo systemctl restart bwf-review
```

The homepage, the Download page and every citation now name the new
version, its date and its DOI. The previous release's database stays in
`published/<its version>/` in the data directory until you delete it.
[Deployment](deployment.md#which-data-it-serves) has the details.

## A release that cannot be rebuilt

Release 1.0.0 was built on 20 September 2026 from commit `50543d9`, with
uncommitted changes. That commit is no longer in the repository, so 1.0.0
has no tag and cannot be rebuilt. Its snapshot was recorded from the
database published on Zenodo:

```bash
uv run brightway-flows release-snapshot --database consensus-flows.sqlite3 \
    --version 1.0.0 --allow-dirty
```

`--allow-dirty` exists for that one case. Do not use it for a new release:
the tag and a clean tree are what let anyone see what built the release.

The snapshot format can change. When it does, the same change extends
`release-snapshot-upgrade` to bring every earlier snapshot up to date from
the files that release published. A format change that needs information no
published file holds would leave the earlier releases without a migration.
Decide in an issue what happens to them before making that change.
[Running a transform](running.md#recording-a-release-and-writing-the-migration-to-the-next-one)
has the options of each command.

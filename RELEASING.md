# Releasing

Pushing a `vX.Y.Z` tag runs [`.github/workflows/release.yml`](.github/workflows/release.yml), which:

1. Builds the sdist and wheel, checks the tag matches `nws_weather_tui.__version__`, and smoke-tests the wheel (installs it and imports every module)
2. Publishes to PyPI through [trusted publishing](https://docs.pypi.org/trusted-publishers/), so no API token is stored in the repo
3. Creates a GitHub release with generated notes and the built files attached

Steps 2 and 3 run independently, so a GitHub release still gets created if PyPI isn't set up yet. The workflow only runs in `crinderneck/nws-weather-tui`. Tags pushed to forks do nothing.

## One-time setup

1. **PyPI pending publisher.** On PyPI, go to *Your account → Publishing → Add a new pending publisher → GitHub* and enter:
   - PyPI project name: `nws-weather-tui`
   - Owner: `crinderneck`
   - Repository name: `nws-weather-tui`
   - Workflow name: `release.yml`
   - Environment name: `pypi`

   A pending publisher doesn't reserve the name. The project is created on the first successful publish.
2. **GitHub environment.** In the repo, go to *Settings → Environments → New environment* and name it `pypi`. Adding yourself as a required reviewer is optional; if you do, every PyPI publish waits for your approval.

## Cutting a release

```bash
# 1. Bump the version
$EDITOR src/nws_weather_tui/__init__.py      # __version__ = "X.Y.Z"
$EDITOR PKGBUILD                              # pkgver=X.Y.Z, pkgrel=1
git commit -am "chore: release vX.Y.Z"
git push

# 2. Tag and push; this starts the workflow
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

When the workflow finishes, users can install with `pipx install nws-weather-tui` or `uv tool install nws-weather-tui`.

## Arch (PKGBUILD)

The PKGBUILD builds from the GitHub tag tarball. After the tag is pushed, fill in the checksum and check that the package builds:

```bash
updpkgsums
makepkg -si
```

Then commit the updated `sha256sums`, and push to the AUR if it's published there.

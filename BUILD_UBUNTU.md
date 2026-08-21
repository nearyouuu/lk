# Ubuntu Build

This project can be built into a Linux Ubuntu release with Nuitka.

## Best option from Windows

Because a Linux binary must be built on Linux, the easiest path from Windows is Docker.

From the project root run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\export_ubuntu_build.ps1
```

This will:

- build a Linux-based Docker builder image
- compile the backend with Nuitka inside Ubuntu-compatible container environment
- extract the final artifact to `dist/ubuntu-release`

## Native build on Ubuntu

Install system packages:

```bash
sudo apt update
sudo apt install -y python3 python3-pip patchelf build-essential ccache
```

Then run:

```bash
bash scripts/build_ubuntu_nuitka.sh
```

## Output

The final folder is:

```text
dist/ubuntu-release
```

It contains:

- `lk_backend` compiled binary
- `start.sh`
- `alembic/`
- `alembic.ini`
- `app/static/`
- prepared `app/media/` directories
- `LICENSE_SETUP.md`
- example license files
- production `Dockerfile.client`, `docker-compose.yml` and `.env.example`
- `CLIENT_DEPLOYMENT.md` with the exact client-server commands

## Run on Ubuntu

Place real files next to the build if needed:

- `license.lic`
- `license_public.pem`
- `.env`

For a native run, then run:

```bash
cd dist/ubuntu-release
./start.sh
```

For the recommended isolated Docker deployment, follow `CLIENT_DEPLOYMENT.md`.

## Notes

- The build is `standalone`, so Python source is not shipped as plain `.py` files.
- This is not perfect protection, but it is much harder to inspect than the raw project.
- `app/static` is included because admin import/export templates are read from disk at runtime.
- User-uploaded files are not embedded into the build; the release only creates the required media folders.

<div align="center">

<a href="https://github.com/AkshatIsWired/lanex/releases/latest"><img src="docs/screenshots/banner.png" alt="LanEx: Verilog to a chip layout. No terminal." width="100%"></a>

[![Latest release](https://img.shields.io/github/v/release/AkshatIsWired/lanex?style=flat-square&color=2f6fe0)](https://github.com/AkshatIsWired/lanex/releases/latest) [![License](https://img.shields.io/badge/license-Apache%202.0-2f6fe0?style=flat-square)](LICENSE) [![Built on LibreLane](https://img.shields.io/badge/built%20on-LibreLane-2f6fe0?style=flat-square)](https://github.com/librelane/librelane)

</div>

LanEx is a desktop app for designing chips with the open-source [LibreLane](https://github.com/librelane/librelane) flow. You write and simulate Verilog, press Run, and get a finished chip layout (a GDS file). If a run fails, LanEx tells you why in plain words and suggests a fix.

## Install

### Windows

**[Download LanEx-Setup.exe](https://github.com/AkshatIsWired/lanex/releases/latest/download/LanEx-Setup.exe)** and run it.

1. If Windows says "Windows protected your PC", click **More info**, then **Run anyway**. The installer isn't code-signed yet.
2. Accept the license, keep **Recommended**, and click **Install**.
3. Your PC may restart once to turn on WSL. Setup opens again by itself after you sign in.

You need Windows 11 or Windows 10 22H2 (64-bit), 8 GB of memory and about 23 GB of free disk space. Setup takes around 15 minutes.

### Linux and macOS

Paste this into a terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install.sh | bash
```

Then start LanEx:

```bash
lanex
```

It works on Ubuntu, Debian, Fedora, Arch, openSUSE and macOS 13 or newer.

Updating, uninstalling, manual installs and troubleshooting are in the [install guide](docs/INSTALL.md).

## Your first chip

Open LanEx and pick **Make my first chip**. It walks you through a small design (a blinking LED) from Verilog to a finished layout in a few minutes.

## What it does

<table>
<tr>
<td width="50%"><img src="docs/screenshots/ide.png" alt="RTL IDE with a simulation waveform"></td>
<td width="50%"><img src="docs/screenshots/pipeline.png" alt="A run with all seven stages finished"></td>
</tr>
<tr>
<td>Write, lint and simulate Verilog, and read the waveform in the app.</td>
<td>Run the flow and watch each stage finish, with a picture of the chip at every step.</td>
</tr>
<tr>
<td><img src="docs/screenshots/fix-sheet.png" alt="A failed run with suggested fixes"></td>
<td><img src="docs/screenshots/layout-3d.png" alt="The finished chip in 3D"></td>
</tr>
<tr>
<td>When a run fails, see what went wrong and apply a fix that resumes the run.</td>
<td>Look at the finished chip layer by layer, or in 3D.</td>
</tr>
</table>

LanEx also lists every check LibreLane runs on the layout, compares runs side by side, and installs the tools and process kits (PDKs) for you. It supports SkyWater 130 nm, GlobalFoundries 180 nm and IHP 130 nm.

## Documentation

- [Install guide](docs/INSTALL.md): every platform, updating, uninstalling, troubleshooting
- [RTL IDE](docs/rtl-ide.md)
- [Verify](docs/verify.md)
- [Layout](docs/layout.md)
- [Cells and macros](docs/cells.md)

## Before you manufacture

LanEx shows what LibreLane and its tools report; it doesn't run its own checks. A "Clean" result means LibreLane's checks passed. Before you send a design to a foundry, run your foundry's and shuttle's own sign-off checks.

## Contributing

Bug reports and ideas are welcome in [Issues](https://github.com/AkshatIsWired/lanex/issues). To run LanEx from source (Python 3.10 or newer):

```bash
git clone https://github.com/AkshatIsWired/lanex && cd lanex
python3 -m venv .venv && . .venv/bin/activate
pip install -c windows/setup/constraints.txt -e . pytest
lanex
```

Run the tests with `python -m pytest lanex/tests -q`.

## License

[Apache 2.0](LICENSE). LanEx is an independent project. It uses LibreLane but isn't affiliated with or endorsed by the LibreLane project. See [NOTICE](NOTICE).

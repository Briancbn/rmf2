# Install from Source (Ubuntu)

## Content

- [Prerequisite](#prerequisite)
  - [Supported System](#supported-system)
  - [Build Tools Setup](#build-tools-setup)
- [Build RMF2 Core Services](#build-rmf2-core-services)
- [Setup RMF2 Web UI](#setup-rmf2-web-ui)

## Prerequisite

### Supported system

- Ubuntu 22.04+
- ROS Humble or Jazzy
- GCC / Clang

### Build Tools Setup

Install python build tool `UV`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install `rust` build tools

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

Install NodeJS and `pnpm`

```bash
curl -fsSL https://get.pnpm.io/install.sh | sh -
source ~/.bashrc
pnpm env use --global 22
```

Additional build dependencies

```bash
sudo apt install python3-tomli-w python3-tomli python3-vcstool
```

Download the extra colcon plugins required for `UV` and local `venv` support.

> [!NOTE]
> We strongly recommend to use a different colcon workspace that the RMF2 repos

```bash
mkdir -p ~/colcon_extra_ws/src
cd ~/colcon_extra_ws
curl -OL <url-todo>
vcs import src < colcon-extras.repos
```

Build the extra colcon plugins
```bash
colcon build
```

## Build RMF2 Core Services

Open a new terminal, so that all build tool configuration is loaded.

Download RMF2 Core Service source code

```bash
mkdir -p ~/rmf2_ws/src
cd ~/rmf2_ws
curl -OL <url-todo>
vcs import src < rmf2.repos
```

Source ROS2 and Build tools
```bash
source /opt/ros/<distro>/setup.bash
source ~/colcon_extra_ws/install/setup.bash
```

Install dependencies

```bash
rosdep install --from-paths src --ignore-src -y
```

Build the source code
```bash
colcon build
```

Setup Python `venv` for the additional python dependencies
```bash
colcon venv sync
```

## Setup RMF2 Web UI

Download RMF2 Web UI source code
```bash
git clone https://github.com/ros-industrial/rmf2-ui.git
```

Install dependencies
```bash
pnpm install
```

Build all `@rmf2-ui/*` packages
```bash
pnpm --filter @rmf2-ui/* build
```

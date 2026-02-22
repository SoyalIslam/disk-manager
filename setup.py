from setuptools import setup, find_packages
from pathlib import Path

# Extract version from src/diskman/__init__.py
version = "0.2.3"
init_file = Path(__file__).parent / "src" / "diskman" / "__init__.py"
if init_file.exists():
    for line in init_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            version = line.split("=")[1].strip().strip('"').strip("'")
            break

setup(
    name="diskman",
    version=version,
    author="Gaffer",
    description="CLI + TUI disk/partition manager with SMART, LUKS, mount controls, and partition operations",
    long_description=Path("README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    url="https://github.com/gaffer/disk-manager",
    project_urls={
        "Homepage": "https://github.com/gaffer/disk-manager",
        "Repository": "https://github.com/gaffer/disk-manager",
        "Issues": "https://github.com/gaffer/disk-manager/issues",
    },
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.9",
    install_requires=[
        "rich>=13.7.0",
    ],
    entry_points={
        "console_scripts": [
            "diskman=diskman.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Systems Administration",
        "Topic :: Utilities",
    ],
    keywords="linux, disk, partition, mount, luks, smart, tui, cli, ntfs3, parted, resize",
)

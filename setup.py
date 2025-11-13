"""Setup configuration for SysDash"""
from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="sysdash",
    version="1.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="Real-time terminal-based system monitoring dashboard with graphs",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/thulasiramk-2310/cli_metrics",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: System Administrators",
        "Topic :: System :: Monitoring",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.7",
    install_requires=[
        "psutil>=5.9.0",
        "rich>=13.0.0",
    ],
    extras_require={
        "backend": ["requests>=2.31.0", "websocket-client>=1.7.0"],
    },
    entry_points={
        "console_scripts": [
            "sysdash=sysdash.cli:main",
            "sysdash-mini=sysdash.cli_mini:main",
        ],
    },
)

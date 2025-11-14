# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy package files
COPY requirements.txt .
COPY setup.py .
COPY pyproject.toml .
COPY README.md .
COPY LICENSE .
COPY sysdash/ ./sysdash/

# Install the package
RUN pip install --no-cache-dir -e .

# Set environment variable to force color output
ENV TERM=xterm-256color

# Default command - run the graphical dashboard
CMD ["sysdash"]

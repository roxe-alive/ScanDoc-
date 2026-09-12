# Use Python 3.10 as the base image
FROM python:3.10-slim

# Set working directory
WORKDIR /DOTSERMODZ

# Install system dependencies
RUN apt-get update && apt-get install -y \
ffmpeg \
tesseract-ocr \
&& rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot source code
COPY . .

# Create directories used by the bot
RUN mkdir -p downloads/compressor

# Start the bot
CMD ["python3", "-m", "dotsermodz"]
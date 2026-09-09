# Use Python 3.10 as the base image
FROM python:3.10-slim

WORKDIR /DOTSERMODZ

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN apt-get update && apt-get install -y tesseract-ocr && rm -rf /var/lib/apt/lists/*

CMD ["python3", "-m", "dotsermodz"]
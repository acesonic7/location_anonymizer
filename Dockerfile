FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY location_anonymizer.py .

RUN useradd --create-home appuser
USER appuser

ENV MPLBACKEND=Agg

ENTRYPOINT ["python", "/app/location_anonymizer.py"]
CMD ["--help"]

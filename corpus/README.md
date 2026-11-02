Place the base corpus of medical PDFs (published research papers and articles) in global/, then run:

    docker compose exec backend python -m scripts.seed_corpus /srv/corpus/global

docker-compose.yaml mounts this folder into the backend at /srv/corpus. PDF files are git-ignored.

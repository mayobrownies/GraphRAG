Place the base corpus of medical PDFs (published research papers and articles) in this folder, then run:

    docker compose exec backend python -m scripts.seed_corpus /srv/corpus

PDF files are git-ignored. Mount this folder into the backend container (see README) before seeding.

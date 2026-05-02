## Authentik/Gateway User Settings

Vocabuildary is designed to sit behind API Get Away at:

```text
https://api-get-away.krishnarajthadesar.in/api/vocabuildary
```

The gateway authenticates with Authentik and injects trusted user headers into
proxied requests:

```text
x-user-sub
x-user-email
x-user-name
```

On each authenticated API request, Vocabuildary upserts a
`vocabuildary_users` row keyed by the stable gateway subject when available,
stores safe identity headers for audit/debugging, and keeps each user's
Telegram bot token and chat id in that row. Bot tokens are never returned by the
API after saving.

The old `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` env vars are now only a
legacy fallback for scheduled sends before any user has configured Telegram in
the UI.

## One-Sided Learning Schedule

Daily sends are planned per user. The global `words` table stores dictionary
metadata such as language, pronunciation, etymology, register, and difficulty.
User-specific learning state lives separately in:

```text
user_learning_settings
user_word_progress
daily_learning_sessions
user_word_exposures
```

Each daily session chooses one new word, a configurable number of review words,
and one optional fill-in-the-blank review. Review words are passed to the LLM so
they can be woven into the new word's paragraph/history as extra encounters. The
blank answer is stored with the session and revealed on the user's next daily
message. Progress percentages are estimated from planned encounters and the
user's configured mastery target, and can be reset per word from the UI/API.

## Book Uploads

Authenticated users can create book upload records through `POST /api/books/uploads`.
The API returns a presigned S3/MinIO `PUT` URL for the source file. After the
browser uploads the PDF, EPUB, or MOBI document, it calls
`POST /api/books/{id}/upload-complete`.

Processing is synchronous for now: `POST /api/books/{id}/process` downloads the
source object, extracts text, counts normalized words, uploads
`word-map.json`, and stores that processed object key on the book row.

Book objects are stored under:

```text
users/{user_id}/books/{book_uuid}/source/{filename}.{ext}
users/{user_id}/books/{book_uuid}/processed/word-map.json
```

Configure object storage with `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`,
`MINIO_SECRET_KEY`, `MINIO_BUCKET`, and `MINIO_REGION`.

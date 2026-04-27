# Economist Lab Mobile

This folder contains the first mobile app scaffold for the vocabulary project.

## Stack

- Expo
- React Native
- TypeScript

## What this first version includes

- onboarding screen for name, persona, and language
- mobile dashboard hooked to the FastAPI backend
- dictionary search screen
- AI instruction vocabulary category screen
- simple profile screen

## API base URL

By default the app uses the deployed site:

`https://economist-vocab.onrender.com`

You can override it with:

```bash
EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

## Local development flow

When you develop the mobile app locally, you usually need **two terminals**:

### Terminal 1: start the FastAPI backend

From the project root:

```bash
cd /Users/lawrencecheng/Documents/New\ project
./start_web.sh
```

This serves the website and the mobile API at:

`http://127.0.0.1:8000`

### Terminal 2: start the mobile app

For web preview on your MacBook:

```bash
cd /Users/lawrencecheng/Documents/New\ project/mobile
npx expo start --web -c
```

Then open:

`http://localhost:8081`

For iPhone testing with Expo Go on the same Wi-Fi:

```bash
cd /Users/lawrencecheng/Documents/New\ project/mobile
npx expo start --host lan -c
```

### Quick reminder

- `127.0.0.1:8000` = FastAPI backend / website
- `localhost:8081` = mobile web preview
- if `localhost:8081` shows `ERR_CONNECTION_REFUSED`, Expo is not running
- if mobile search says `Failed to fetch`, check whether the backend is running

## Start the app

```bash
cd /Users/lawrencecheng/Documents/New\ project/mobile
npm install
npm run start
```

Then open in Expo Go, iOS Simulator, or Android Emulator.

## Current mobile API endpoints

- `/api/mobile/bootstrap`
- `/api/mobile/dictionary/search`
- `/api/mobile/word/{word_id}`
- `/api/mobile/ai-power/categories`
- `/api/mobile/ai-power/category/{category_slug}`
- `/api/mobile/ai-power/category/{category_slug}/{entry_slug}`

## Recommended next steps

1. add real navigation and screen files
2. add learning session APIs for the app
3. add saved progress and local persistence
4. add pronunciation playback in mobile

# Golf Shot Tracker

Clean, modular golf shot data extraction app with AI processing.

## 🚀 Deploy to Render

### 1. Push to GitHub
```bash
# Add your GitHub repo (create it first on github.com)
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
git push -u origin main
```

### 2. Deploy Backend
1. Go to [render.com](https://render.com)
2. New > Web Service
3. Connect this repo
4. Name: `golf-shot-api` (or your choice)
5. Start Command: `gunicorn api:app --bind 0.0.0.0:$PORT`
6. Add environment variables:
   - `OPENAI_API_KEY`
   - `GOOGLE_API_KEY` 
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `REDIS_HOST` (use Render Redis)
   - `REDIS_PORT=6379`
   - `SECRET_KEY` (generate random string)

### 3. Deploy Frontend
1. New > Static Site
2. Connect same repo
3. Name: `golf-shot-frontend`
4. Publish directory: `.`

### 4. Update Frontend
Edit `app.html` line ~439:
```javascript
: 'https://golf-shot-api.onrender.com';  // Your backend URL
```

### 5. Configure Google OAuth
Add to redirect URIs:
```
https://golf-shot-api.onrender.com/auth/callback
```

## ✅ Done!
Visit your frontend URL to start using the app. 
import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import cookieParser from 'cookie-parser';
import path from 'path';
import { fileURLToPath } from 'url';

// Routes
import fitRoutes from './routes/fit.routes.js';
import simulationRoutes from './routes/simulation.routes.js';
import profileRoutes from './routes/profile.routes.js';
import powerCurveRoutes from './routes/powerCurve.routes.js';
import trackRoutes from './routes/track.routes.js';
import stravaRoutes from './routes/strava.routes.js';
import optimizerRoutes from './routes/optimizer.routes.js';

const app = express();
const PORT = process.env.PORT || 3001;

// Middleware - CORS configuration for web and mobile
app.use(cors({
  origin: (origin, callback) => {
    // Allow requests with no origin (mobile apps, curl, etc.)
    if (!origin) {
      return callback(null, true);
    }

    // Allow localhost and local network IPs for development
    if (origin.includes('localhost') || origin.includes('127.0.0.1') || origin.includes('192.168.')) {
      return callback(null, true);
    }

    // Allow ngrok tunnels for Expo mobile
    if (origin.includes('ngrok') || origin.includes('ngrok-free')) {
      return callback(null, true);
    }

    // Allow Expo development servers
    if (origin.includes('expo') || origin.includes('exp://')) {
      return callback(null, true);
    }

    // Default: allow configured client URL
    const allowedOrigin = process.env.CLIENT_URL || 'http://localhost:5173';
    if (origin === allowedOrigin) {
      return callback(null, true);
    }

    // Reject other origins
    callback(new Error('Not allowed by CORS'));
  },
  credentials: true, // Allow cookies for Strava session
}));
app.use(cookieParser());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true }));

// API Routes
app.use('/api/fit', fitRoutes);
app.use('/api/simulation', simulationRoutes);
app.use('/api/profile', profileRoutes);
app.use('/api/power-curve', powerCurveRoutes);
app.use('/api/track', trackRoutes);
app.use('/api/strava', stravaRoutes);
app.use('/api/optimizer', optimizerRoutes);

// Health check
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Error handling middleware
app.use((err: Error, req: express.Request, res: express.Response, next: express.NextFunction) => {
  console.error('Error:', err.message);
  res.status(500).json({ error: err.message });
});

app.listen(PORT, () => {
  console.log(`Flying 200m server running at http://localhost:${PORT}`);
  console.log(`Health check: http://localhost:${PORT}/api/health`);
});

const express = require("express");
const uuidv4 = require('uuid').v4;
const session = require("express-session");
const cookieParser = require('cookie-parser');
const bcrypt = require('bcrypt');
const bodyParser = require('body-parser');
const jwt = require("jsonwebtoken");
const sqlite3 = require("sqlite3").verbose();
const cors = require("cors");
const path = require("path");
const fs = require('fs');
const { initializeDatabase } = require('./setup');


const app = express();

app.use(express.json());
app.use(cors({
    origin: "http://localhost:5500", // front-end URL
    credentials: true
}));
app.use(bodyParser.urlencoded({ extended: true }));
app.use(cookieParser());
app.use(session({
    secret: 'secret-key',
    resave: false,
    saveUninitialized: true,
    cookie: { maxAge: 60 * 60 * 1000 }
}));

app.use(express.static("views"));


const dbPath = path.join(__dirname, "flights.db");

//Open Database
const db = new sqlite3.Database(dbPath, async (err) => {
  if (err) return console.error("Database connection error:", err.message);
  console.log("Connected to flights.db");

  // Initialize database tables if they don't exist
  try {
    await initializeDatabase(db);
  } catch (err) {
    console.error("Database initialization error:", err.message);
  }
});

// ----------------------
// ROUTES
// ----------------------
app.get('/', (req, res) => {
    res.sendFile(path.join(__dirname, "views", "main-page.html"));
});

app.get('/account', (req, res) => {
    res.sendFile(path.join(__dirname, "views", "login-page.html"));
});

// ----------------------
// REGISTER
// ----------------------
app.post("/api/auth/register", (req, res) => {
    const { first_name, last_name, email, password, confirmPassword } = req.body;

    if (!first_name || !last_name || !email || !password || !confirmPassword) {
        return res.status(400).json({ message: "Missing fields" });
    }

    if (password !== confirmPassword) {
        return res.status(400).json({ message: "Passwords do not match" });
    }

    db.get("SELECT email FROM Users WHERE email = ?", [email], async (err, row) => {
        if (err) return res.status(500).json({ message: "Database error: " + err.message });

        if (row) return res.status(409).json({ message: "Email already registered" });

        try {
            const hashed = await bcrypt.hash(password, 10);
            const userId = uuidv4();

            db.run(
                "INSERT INTO Users (user_id, first_name, last_name, email, password_hash) VALUES (?, ?, ?, ?, ?)",
                [userId, first_name, last_name, email, hashed],
                function (err) {
                    if (err) return res.status(500).json({ message: "Database error: " + err.message });

                    return res.status(201).json({
                        message: "User registered successfully",
                        user_id: userId
                    });
                }
            );
        } catch (err) {
            return res.status(500).json({ message: "Server error: " + err.message });
        }
    });
});

// ----------------------
// LOGIN
// ----------------------
app.post("/api/auth/login", (req, res) => {
    const { email, password } = req.body;

    if (!email || !password)
        return res.status(400).json({ message: "Missing fields" });

    db.get("SELECT * FROM Users WHERE email = ?", [email], async (err, user) => {
        if (err) {
            console.error(err);
            return res.status(500).json({ message: "Database error" });
        }

        if (!user) return res.status(404).json({ message: "User not found" });

        const valid = await bcrypt.compare(password, user.password_hash);
        if (!valid) return res.status(401).json({ message: "Invalid password" });

        const token = jwt.sign(
            { id: user.user_id, email: user.email, role: user.role },
            "SECRET_KEY",
            { expiresIn: "1d" }
        );

        return res.json({
            message: "Login successful",
            token,
            user: {
                id: user.user_id,
                first_name: user.first_name,
                last_name: user.last_name,
                email: user.email,
                role: user.role
            }
        });
    });
});

// ----------------------
app.listen(3000, () => console.log("Server running on http://localhost:3000"));
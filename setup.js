const sqlite3 = require("sqlite3").verbose();
const fs = require("fs");
const path = require("path");

function initializeDatabase(db) {
  return new Promise((resolve, reject) => {
    const sqlPath = path.join(__dirname, "database.sql");
    let sql;
    try {
      sql = fs.readFileSync(sqlPath, "utf8");
    } catch (err) {
      return reject(new Error("Cannot read database.sql: " + err.message));
    }

    const statements = sql.split(";").map(s => s.trim()).filter(s => s.length > 0);

    let completed = 0;
    let hasError = false;
    
    statements.forEach((stmt, index) => {
      db.run(stmt, function(err) {
        if (err) {
          // IF NOT EXISTS errors are acceptable (table already exists)
          if (!err.message.includes("already exists")) {
            console.error(`Error in statement ${index + 1}:`, err.message);
            hasError = true;
          }
        } else {
          console.log(`Statement ${index + 1} executed successfully.`);
        }
        completed++;
        if (completed === statements.length) {
          if (hasError) reject(new Error("Database initialization had errors"));
          else {
            console.log("Database initialized successfully.");
            resolve();
          }
        }
      });
    });
  });
}

module.exports = { initializeDatabase };
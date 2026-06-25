TEST_DIR=/tmp/openhealth-react-vite-smoke
rm -rf "$TEST_DIR"
mkdir -p "$TEST_DIR/src"
cd "$TEST_DIR"

cat > package.json <<'EOF'
{
  "name": "openhealth-react-vite-smoke",
  "private": true,
  "version": "0.0.0-smoke",
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5173",
    "build": "vite build",
    "preview": "vite preview --host 127.0.0.1 --port 4173"
  },
  "dependencies": {
    "@vitejs/plugin-react": "4.2.1",
    "vite": "5.4.11",
    "react": "18.2.0",
    "react-dom": "18.2.0"
  },
  "devDependencies": {}
}
EOF

cat > index.html <<'EOF'
<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <title>React Vite Smoke Test</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
EOF

cat > src/main.jsx <<'EOF'
import React from "react";
import { createRoot } from "react-dom/client";

function App() {
  return (
    <main style={{ fontFamily: "Arial, sans-serif", padding: 32 }}>
      <h1>React + Vite smoke test</h1>
      <p id="status">React is mounted and Vite is serving.</p>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
EOF

npm install
npm run build

npm run dev > vite.log 2>&1 &
VITE_PID=$!

sleep 3
curl -fsS http://127.0.0.1:5173 | grep -q "root" && echo "Vite dev server is responding"

kill "$VITE_PID"
import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// All Python modules are now consolidated in the server's python folder
const PYTHON_DIR = path.resolve(__dirname, '../../python');

export interface PythonResult<T = unknown> {
  success: boolean;
  data?: T;
  error?: string;
}

/**
 * Execute a Python script and return the JSON result
 */
export async function runPythonScript<T = unknown>(
  scriptName: string,
  input: unknown
): Promise<PythonResult<T>> {
  return new Promise((resolve) => {
    const scriptPath = path.join(PYTHON_DIR, scriptName);
    // Use python3 for Linux containers, python for Windows
    const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';

    console.log(`[Python] Running: ${pythonCmd} ${scriptPath}`);
    console.log(`[Python] CWD: ${PYTHON_DIR}`);

    const python = spawn(pythonCmd, [scriptPath], {
      cwd: PYTHON_DIR,
      env: {
        ...process.env,
        PYTHONPATH: PYTHON_DIR,
      },
    });

    let stdout = '';
    let stderr = '';

    // Send input as JSON via stdin
    python.stdin.write(JSON.stringify(input));
    python.stdin.end();

    python.stdout.on('data', (data) => {
      stdout += data.toString();
    });

    python.stderr.on('data', (data) => {
      const chunk = data.toString();
      stderr += chunk;
      // Log stderr in real-time for debugging
      console.log(`[Python] ${chunk.trimEnd()}`);
    });

    python.on('close', (code) => {
      console.log(`[Python] Exit code: ${code}`);
      if (code === 0) {
        try {
          const result = JSON.parse(stdout);
          resolve({ success: true, data: result });
        } catch (e) {
          console.log(`[Python] Failed to parse output: ${stdout.substring(0, 500)}`);
          resolve({
            success: false,
            error: `Failed to parse Python output: ${stdout.substring(0, 500)}`
          });
        }
      } else {
        console.log(`[Python] Error: ${stderr || `Exit code ${code}`}`);
        resolve({
          success: false,
          error: stderr || `Python script exited with code ${code}`
        });
      }
    });

    python.on('error', (err) => {
      console.log(`[Python] Spawn error: ${err.message}`);
      resolve({ success: false, error: err.message });
    });
  });
}

/**
 * Execute a Python script with a file path argument
 */
export async function runPythonScriptWithFile<T = unknown>(
  scriptName: string,
  filePath: string,
  additionalInput?: unknown
): Promise<PythonResult<T>> {
  const input = {
    file_path: filePath,
    ...(additionalInput || {}),
  };
  return runPythonScript<T>(scriptName, input);
}

/**
 * Execute a Python script with streaming output
 * Calls onProgress for each line of stdout (for progress updates)
 * Returns final result when script completes
 */
export async function runPythonScriptStreaming<T = unknown>(
  scriptName: string,
  input: unknown,
  onProgress: (line: string) => void
): Promise<PythonResult<T>> {
  return new Promise((resolve) => {
    const scriptPath = path.join(PYTHON_DIR, scriptName);
    const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';

    const python = spawn(pythonCmd, [scriptPath], {
      cwd: PYTHON_DIR,
      env: {
        ...process.env,
        PYTHONPATH: PYTHON_DIR,
      },
    });

    let lastLine = '';
    let stderr = '';

    // Send input as JSON via stdin
    python.stdin.write(JSON.stringify(input));
    python.stdin.end();

    // Stream stdout line by line
    python.stdout.on('data', (data) => {
      const lines = data.toString().split('\n');
      for (const line of lines) {
        if (line.trim()) {
          lastLine = line;
          onProgress(line);
        }
      }
    });

    python.stderr.on('data', (data) => {
      const chunk = data.toString();
      stderr += chunk;
      // Log stderr in real-time for debugging
      console.log(`[Python] ${chunk.trimEnd()}`);
    });

    python.on('close', (code) => {
      if (code === 0) {
        try {
          // The last line should be the final JSON result
          const result = JSON.parse(lastLine);
          resolve({ success: true, data: result });
        } catch (e) {
          resolve({
            success: false,
            error: `Failed to parse Python output: ${lastLine.substring(0, 500)}`
          });
        }
      } else {
        resolve({
          success: false,
          error: stderr || `Python script exited with code ${code}`
        });
      }
    });

    python.on('error', (err) => {
      resolve({ success: false, error: err.message });
    });
  });
}

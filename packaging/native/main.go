// The release entrypoint. Cached statusline ticks never start Python.
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unicode"
)

func atomicWrite(path string, b []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".native-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(b); err != nil {
		f.Close()
		return err
	}
	if err = f.Close(); err != nil {
		return err
	}
	return os.Rename(f.Name(), path)
}

func sessionID(d map[string]any) string {
	s, _ := d["session_id"].(string)
	var b []rune
	for _, r := range s {
		if unicode.IsLetter(r) || unicode.IsNumber(r) || r == '-' || r == '_' {
			b = append(b, r)
			if len(b) == 64 {
				break
			}
		}
	}
	if len(b) == 0 {
		return "default"
	}
	return string(b)
}

type meta struct {
	Generated float64 `json:"generated_at"`
	Started   float64 `json:"daemon_started_at"`
	Window    float64 `json:"stale_after_seconds"`
	Native    int     `json:"native_protocol"`
	Columns   string  `json:"columns"`
	PID       int     `json:"pid"`
}

func cached(root, runtime string, d map[string]any) bool {
	sid := sessionID(d)
	env := map[string]string{}
	for _, k := range []string{"ANTHROPIC_BASE_URL", "CS_API_MODE", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "COLUMNS"} {
		if v := os.Getenv(k); v != "" {
			env[k] = v
		}
	}
	d["_cs_env"] = env
	b, err := json.Marshal(d)
	if err != nil {
		return false
	}
	dir := filepath.Join(root, "sessions", sid)
	// Heartbeat is the input mtime; unchanged payloads need no rewrite.
	input := filepath.Join(dir, "last_stdin.json")
	prev, _ := os.ReadFile(input)
	if bytes.Equal(prev, b) {
		now := time.Now()
		err = os.Chtimes(input, now, now)
	} else {
		err = atomicWrite(input, b)
	}
	if err != nil {
		return false
	}
	legacy := filepath.Join(root, "last_stdin.json")
	if st, e := os.Stat(legacy); e != nil || time.Since(st.ModTime()) > 5*time.Second {
		_ = atomicWrite(legacy, b)
	}
	var m meta
	b, err = os.ReadFile(filepath.Join(dir, "rendered.meta.json"))
	if err != nil || json.Unmarshal(b, &m) != nil {
		return false
	}
	if m.Native != 1 || m.Columns != env["COLUMNS"] || m.Window <= 0 || m.Window > 30 || m.PID <= 1 {
		return false
	}
	age := float64(time.Now().UnixNano())/1e9 - m.Generated
	if age < 0 || age > m.Window+30 {
		return false
	}
	if st, e := os.Stat(runtime); e != nil || float64(st.ModTime().UnixNano())/1e9 > m.Started {
		return false
	}
	if syscall.Kill(m.PID, 0) != nil {
		return false
	}
	// Leave unusual/displaced settings to the compatibility implementation.
	home, _ := os.UserHomeDir()
	var settings struct {
		StatusLine struct {
			Command string `json:"command"`
		} `json:"statusLine"`
	}
	if b, e := os.ReadFile(filepath.Join(home, ".claude", "settings.json")); e == nil {
		if json.Unmarshal(b, &settings) == nil && settings.StatusLine.Command != "" {
			fields := strings.Fields(settings.StatusLine.Command)
			name := filepath.Base(strings.Trim(fields[0], "\"'"))
			if name != "cs" && name != "cstatus" && name != "claude-statusbar" {
				return false
			}
		}
	}
	b, err = os.ReadFile(filepath.Join(dir, "rendered.ansi"))
	if err != nil {
		return false
	}
	if age > m.Window {
		b = append(bytes.TrimRight(b, "\n"), []byte(" \x1b[2m⟳\x1b[0m\n")...)
	}
	_, err = os.Stdout.Write(b)
	return err == nil
}

func main() {
	self, err := os.Executable()
	if err != nil {
		os.Exit(1)
	}
	self, err = filepath.EvalSymlinks(self)
	if err != nil {
		os.Exit(1)
	}
	runtime := filepath.Join(filepath.Dir(self), "cs-python")
	args := os.Args[1:]
	if len(args) != 1 || args[0] != "render" {
		if err = syscall.Exec(runtime, append([]string{os.Args[0]}, args...), os.Environ()); err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
	}
	// Decode one document, not EOF: the host may retain the pipe writer.
	var raw json.RawMessage
	reader := io.LimitReader(os.Stdin, 4<<20)
	err = json.NewDecoder(reader).Decode(&raw)
	var d map[string]any
	if err == nil && json.Unmarshal(raw, &d) == nil && d != nil {
		home, e := os.UserHomeDir()
		if e == nil && cached(filepath.Join(home, ".cache", "claude-statusbar"), runtime, d) {
			trace("cache")
			return
		}
	}
	cmd := exec.Command(runtime, args...)
	home, _ := os.UserHomeDir()
	root := filepath.Join(home, ".cache", "claude-statusbar")
	slot := bootstrapSlot(root)
	if slot == nil {
		trace("shed")
		fmt.Fprintln(os.Stdout, "cs: warming up…")
		return
	}
	defer slot.Close()
	// Keep the lock in the child too if the host kills the native parent.
	cmd.ExtraFiles = []*os.File{slot}
	trace("python")
	cmd.Stdin = bytes.NewReader(raw)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err = cmd.Run(); err != nil {
		if e, ok := err.(*exec.ExitError); ok {
			os.Exit(e.ExitCode())
		}
		os.Exit(1)
	}
}

func bootstrapSlot(root string) *os.File {
	if os.MkdirAll(root, 0700) != nil {
		return nil
	}
	for i := 0; i < 2; i++ {
		f, e := os.OpenFile(filepath.Join(root, fmt.Sprintf("native.bootstrap.%d", i)), os.O_CREATE|os.O_RDWR, 0600)
		if e != nil {
			continue
		}
		if syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB) == nil {
			return f
		}
		f.Close()
	}
	return nil
}

// Opt-in diagnostics contain only a route, never payloads or credentials.
func trace(route string) {
	if dir := os.Getenv("CS_PERF_TRACE_DIR"); dir != "" {
		_ = atomicWrite(filepath.Join(dir, fmt.Sprintf("%d.json", os.Getpid())), []byte(fmt.Sprintf("{\"route\":%q}", route)))
	}
}

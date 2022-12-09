package main

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"
)

const initial=65535
const overhead=28

func parseHint(data string) (int, error) {
	data = strings.ReplaceAll(data, "\n", " ")
	data = strings.ReplaceAll(data, "\t", " ")
	items := strings.Split(data, " ")
	for _, it := range items {
		if !strings.Contains(it, "mtu=") {
			continue
		}
		it = it[4:]
		hint, err := strconv.ParseInt(it, 10, 16)
		if err != nil {
			return 0, fmt.Errorf("failed to parse `%s`: %w", it, err)
		}
		return int(hint), nil
	}
	return 0, fmt.Errorf("mtu= hint not found in output")
}

func tryLen(len int, dest string) (int, error) {
	cmd := exec.Command("ping", "-M", "do", "-s", strconv.Itoa(len - overhead), "-c", "5", dest)
	outBytes, err := cmd.CombinedOutput()
	if err != nil {
		_, isErrExit := err.(*exec.ExitError)
		if !isErrExit {
			return 0, fmt.Errorf("failed to execute ping: %w", err)
		}
	}
	out := string(outBytes)
	if strings.Contains(out, "ttl=") {
		return len, nil
	}
	if !strings.Contains(out, "mtu=") {
		return 0, fmt.Errorf("unexpected output (may be caused by invalid or unreachable address):\n%s", out)
	}
	newLen, err := parseHint(out)
	if err != nil {
		return 0, fmt.Errorf("failed to parse hint: %w", err)
	}
	if newLen >= len {
		return 0, fmt.Errorf("parsed hint %d is more then current estimate %d", newLen, len)
	}
	if newLen < 68 {
		return 0, fmt.Errorf("parsed MTU hint %d violates IP standard", newLen)
	}
	return newLen, nil
}

func main() {
	args := os.Args
	if len(args) != 2 {
		fmt.Printf("Usage: %s <target>\n", args[0])
		os.Exit(2)
	}
	target := args[1]
	conn, err := net.Dial("ip4:1", target)
	if err != nil {
		fmt.Printf("warning: failed to dial %s, it is likely invalid: %v\n", target, err)
	} else {
	    conn.Close()
	}

	len := initial
	for {
		newLen, err := tryLen(len, target)
		if err != nil {
			fmt.Printf("error: %v", err)
			os.Exit(1)
		}
		if len == newLen {
			break
		}
		fmt.Printf("%d -> %d\n", len, newLen)
		len = newLen
	}
	fmt.Printf("Path MTU is %d\n", len)
}

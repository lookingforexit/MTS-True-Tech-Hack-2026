package config

import (
	"os"
)

type Config struct {
	Port      string
	AgentAddr string
}

func LoadConfig() *Config {
	return &Config{
		Port:      getEnv("BACKEND_PORT", "5252"),
		AgentAddr: getEnv("AGENT_ADDR", "6767"),
	}
}

func getEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

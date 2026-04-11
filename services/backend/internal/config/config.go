package config

import (
	"os"
)

type Config struct {
	Port    string
	LLMAddr string
}

func LoadConfig() *Config {
	return &Config{
		Port:    getEnv("BACKEND_PORT", "8080"),
		LLMAddr: getEnv("LLM_ADDR", "localhost:50051"),
	}
}

func getEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

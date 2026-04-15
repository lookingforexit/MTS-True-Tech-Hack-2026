package config

import (
	"os"
)

type Config struct {
	Port string
}

func LoadConfig() *Config {
	return &Config{
		Port: getEnv("PORT", "50053"),
	}
}

func getEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

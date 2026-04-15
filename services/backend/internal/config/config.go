package config

import (
	"os"
	"time"
)

type Config struct {
	Port              string
	LLMAddr           string
	RedisAddr         string
	PipelineStateTTL  time.Duration
	SessionLockTTL    time.Duration
	LLMRequestTimeout time.Duration
}

func LoadConfig() *Config {
	sessionLockTTL := getDurationEnv("SESSION_LOCK_TTL", 20*time.Minute)
	pipelineStateTTL := getDurationEnv("PIPELINE_STATE_TTL", 24*time.Hour)
	if pipelineStateTTL <= sessionLockTTL {
		pipelineStateTTL = sessionLockTTL + time.Hour
	}

	llmRequestTimeout := getDurationEnv("LLM_REQUEST_TIMEOUT", 15*time.Minute)
	if llmRequestTimeout >= sessionLockTTL && sessionLockTTL > time.Minute {
		llmRequestTimeout = sessionLockTTL - time.Minute
	}
	if llmRequestTimeout <= 0 {
		llmRequestTimeout = sessionLockTTL
	}

	return &Config{
		Port:              getEnv("BACKEND_PORT", "8080"),
		LLMAddr:           getEnv("LLM_ADDR", "localhost:50051"),
		RedisAddr:         getEnv("REDIS_ADDR", "localhost:6379"),
		PipelineStateTTL:  pipelineStateTTL,
		SessionLockTTL:    sessionLockTTL,
		LLMRequestTimeout: llmRequestTimeout,
	}
}

func getEnv(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}

func getDurationEnv(key string, fallback time.Duration) time.Duration {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	parsed, err := time.ParseDuration(value)
	if err != nil {
		return fallback
	}
	return parsed
}

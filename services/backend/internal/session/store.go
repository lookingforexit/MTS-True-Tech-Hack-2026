package session

import (
	"context"
	"errors"
	"time"

	llmv1 "backend/gen/llm/v1"

	"github.com/redis/go-redis/v9"
	"google.golang.org/protobuf/proto"
)

type Store struct {
	redisDB *redis.Client
	timeout time.Duration
}

func NewStore(addr string, timeout time.Duration) *Store {
	return &Store{
		redisDB: redis.NewClient(&redis.Options{Addr: addr}),
		timeout: timeout,
	}
}

func key(sessionID string) string {
	return "pipeline_state:" + sessionID
}

func lockKey(sessionID string) string {
	return "pipeline_state_lock:" + sessionID
}

func (s *Store) Get(ctx context.Context, sessionID string) (*llmv1.PipelineState, error) {
	if sessionID == "" {
		return nil, nil
	}

	data, err := s.redisDB.Get(ctx, key(sessionID)).Bytes()
	if err != nil {
		if errors.Is(err, redis.Nil) {
			return nil, nil
		}
		return nil, err
	}

	var state llmv1.PipelineState
	if err := proto.Unmarshal(data, &state); err != nil {
		return nil, err
	}

	return &state, nil
}

func (s *Store) Save(ctx context.Context, sessionID string, state *llmv1.PipelineState) error {
	if sessionID == "" || state == nil {
		return errors.New("session id and state required")
	}

	data, err := proto.Marshal(state)
	if err != nil {
		return err
	}

	return s.redisDB.Set(ctx, key(sessionID), data, s.timeout).Err()
}

func (s *Store) Ping(ctx context.Context) error {
	return s.redisDB.Ping(ctx).Err()
}

func (s *Store) Lock(ctx context.Context, sessionID, token string, timeout time.Duration) (bool, error) {
	if sessionID == "" || token == "" {
		return false, errors.New("session id and lock token required")
	}
	return s.redisDB.SetNX(ctx, lockKey(sessionID), token, timeout).Result()
}

func (s *Store) Unlock(ctx context.Context, sessionID, token string) error {
	if sessionID == "" || token == "" {
		return errors.New("session id and lock token required")
	}

	const script = `
if redis.call("GET", KEYS[1]) == ARGV[1] then
	return redis.call("DEL", KEYS[1])
end
return 0
`
	return s.redisDB.Eval(ctx, script, []string{lockKey(sessionID)}, token).Err()
}

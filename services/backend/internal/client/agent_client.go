package client

import (
	agent "backend/gen/agent/v1"
	"context"
	"google.golang.org/grpc"
)

type AgentClient struct {
	agent agent.AgentServiceClient
}

func NewAgentClient(conn *grpc.ClientConn) *AgentClient {
	return &AgentClient{agent: agent.NewAgentServiceClient(conn)}
}

func (a *AgentClient) Generate(ctx context.Context, sessionID, task, contextJSON, mode string) (*agent.GenerateResponse, error) {
	resp, err := a.agent.Generate(ctx, &agent.GenerateRequest{
		SessionId:   sessionID,
		Task:        task,
		ContextJson: contextJSON,
		Mode:        mode,
	})
	if err != nil {
		return nil, err
	}

	return resp, nil
}

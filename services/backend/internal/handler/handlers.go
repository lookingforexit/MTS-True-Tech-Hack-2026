package handler

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	llmv1 "backend/gen/llm/v1"
	"backend/internal/session"

	"github.com/gin-gonic/gin"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// HealthHandler returns a health check response and verifies Redis connectivity.
func HealthHandler(stateStore *session.Store) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		if err := stateStore.Ping(ctx.Request.Context()); err != nil {
			ctx.JSON(http.StatusServiceUnavailable, gin.H{
				"status": "unhealthy",
				"redis":  err.Error(),
			})
			return
		}
		ctx.JSON(http.StatusOK, gin.H{"status": "ok"})
	}
}

type GenerateRequest struct {
	Prompt              string          `json:"prompt"`
	SessionID           string          `json:"session_id,omitempty"`
	ClarificationAnswer string          `json:"clarification_answer,omitempty"`
	Mode                string          `json:"mode,omitempty"`
	Context             json.RawMessage `json:"context,omitempty"`
}

type GenerateResponse struct {
	Code             string `json:"code,omitempty"`
	Question         string `json:"question,omitempty"`
	SessionID        string `json:"session_id,omitempty"`
	Error            string `json:"error,omitempty"`
	RepairCount      int32  `json:"repair_count,omitempty"`
	ValidationOutput string `json:"validation_output,omitempty"`
	ValidationError  string `json:"validation_error,omitempty"`
}

func wrapLuaTransport(raw string) string {
	if raw == "" {
		return ""
	}
	trimmed := strings.TrimSpace(raw)
	if strings.HasPrefix(trimmed, "lua{") && strings.HasSuffix(trimmed, "}lua") {
		return raw
	}
	return fmt.Sprintf("lua{%s}lua", raw)
}

func wrapTextTransport(raw string) string {
	if raw == "" {
		return ""
	}
	trimmed := strings.TrimSpace(raw)
	if strings.HasPrefix(trimmed, "text{") && strings.HasSuffix(trimmed, "}text") {
		return raw
	}
	return fmt.Sprintf("text{%s}text", raw)
}

func newSessionID() (string, error) {
	var buf [16]byte
	if _, err := rand.Read(buf[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(buf[:]), nil
}

func looksLikeClarificationAnswer(prompt, question string) bool {
	trimmed := strings.TrimSpace(prompt)
	if trimmed == "" {
		return false
	}
	if strings.Contains(trimmed, "wf.vars.") || strings.Contains(trimmed, "wf.initVariables.") {
		return true
	}

	loweredPrompt := strings.ToLower(trimmed)
	loweredQuestion := strings.ToLower(strings.TrimSpace(question))
	if strings.Contains(loweredQuestion, "return") || strings.Contains(loweredQuestion, "возвращ") {
		return len(strings.Fields(trimmed)) <= 10
	}
	if strings.Contains(loweredQuestion, "path") || strings.Contains(loweredQuestion, "путь") {
		if len(strings.Fields(trimmed)) <= 8 {
			return true
		}
	}

	newRequestMarkers := []string{
		"write", "implement", "generate", "convert", "sort", "filter",
		"напиши", "реализуй", "сгенерируй", "конвертируй", "отсортируй", "сделай",
	}
	for _, marker := range newRequestMarkers {
		if strings.Contains(loweredPrompt, marker) {
			return false
		}
	}

	return len(strings.Fields(trimmed)) <= 6
}

func Handler(client llmv1.LLMServiceClient, stateStore *session.Store) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		var req GenerateRequest
		if err := ctx.ShouldBindJSON(&req); err != nil {
			ctx.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
			return
		}
		if req.ClarificationAnswer != "" && req.SessionID == "" {
			ctx.JSON(http.StatusBadRequest, gin.H{"error": "session_id is required with clarification_answer"})
			return
		}
		if req.ClarificationAnswer == "" && req.Prompt == "" {
			ctx.JSON(http.StatusBadRequest, gin.H{"error": "prompt is required unless sending clarification_answer"})
			return
		}
		if req.SessionID == "" {
			sessionID, err := newSessionID()
			if err != nil {
				ctx.JSON(http.StatusInternalServerError, gin.H{"error": "failed to generate session_id: " + err.Error()})
				return
			}
			req.SessionID = sessionID
		}

		if len(req.Context) > 0 {
			var parsed map[string]interface{}
			if err := json.Unmarshal(req.Context, &parsed); err != nil {
				ctx.JSON(http.StatusBadRequest, gin.H{"error": "context must be valid JSON object: " + err.Error()})
				return
			}
		}

		rpcCtx, cancel := context.WithTimeout(ctx.Request.Context(), 900*time.Second)
		defer cancel()

		var resp *llmv1.SessionResponse
		var err error

		lockToken, err := newSessionID()
		if err != nil {
			ctx.JSON(http.StatusInternalServerError, gin.H{"error": "failed to generate lock token: " + err.Error()})
			return
		}

		locked, err := stateStore.Lock(rpcCtx, req.SessionID, lockToken, 20*time.Minute)
		if err != nil {
			ctx.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		if !locked {
			ctx.JSON(http.StatusConflict, GenerateResponse{Error: "session is already processing"})
			return
		}
		defer func() {
			_ = stateStore.Unlock(context.Background(), req.SessionID, lockToken)
		}()

		pipelineState, err := stateStore.Get(rpcCtx, req.SessionID)
		if err != nil {
			ctx.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}

		if req.ClarificationAnswer != "" {
			if pipelineState == nil {
				ctx.JSON(http.StatusNotFound, GenerateResponse{Error: "session state not found"})
				return
			}
			resp, err = client.AnswerClarification(rpcCtx, &llmv1.AnswerRequest{
				SessionId:     req.SessionID,
				Answer:        req.ClarificationAnswer,
				PipelineState: pipelineState,
			})
		} else {
			if pipelineState == nil {
				pipelineState = &llmv1.PipelineState{
					SessionId: req.SessionID,
					Request:   req.Prompt,
				}
				if len(req.Context) > 0 {
					contextValue := string(req.Context)
					pipelineState.Context = &contextValue
				}
			} else if pipelineState.GetPhase() == "clarification_needed" {
				if req.Mode == "new_request" || !looksLikeClarificationAnswer(req.Prompt, pipelineState.GetClarificationQuestion()) {
					pipelineState = &llmv1.PipelineState{
						SessionId: req.SessionID,
						Request:   req.Prompt,
					}
					if len(req.Context) > 0 {
						contextValue := string(req.Context)
						pipelineState.Context = &contextValue
					}
				} else {
					ctx.JSON(http.StatusConflict, GenerateResponse{Error: "session is waiting for clarification_answer"})
					return
				}
			}
			resp, err = client.StartOrContinue(rpcCtx, &llmv1.SessionRequest{
				PipelineState: pipelineState,
			})
		}

		if err != nil {
			st, _ := status.FromError(err)
			code := http.StatusBadGateway
			if st.Code() == codes.NotFound {
				code = http.StatusNotFound
			} else if st.Code() == codes.FailedPrecondition {
				code = http.StatusConflict
			}
			ctx.JSON(code, GenerateResponse{Error: err.Error()})
			return
		}

		state := resp.GetPipelineState()
		if state == nil {
			ctx.JSON(http.StatusBadGateway, GenerateResponse{Error: "LLM response has no pipeline_state"})
			return
		}

		if err := stateStore.Save(rpcCtx, state.GetSessionId(), state); err != nil {
			ctx.JSON(http.StatusInternalServerError, GenerateResponse{Error: err.Error()})
			return
		}

		out := GenerateResponse{SessionID: state.GetSessionId()}

		switch state.GetPhase() {
		case "clarification_needed":
			out.Question = wrapTextTransport(state.GetClarificationQuestion())
		case "done":
			out.Code = wrapLuaTransport(state.GetCode())
		case "error":
			out.Error = state.GetError()
			out.ValidationError = state.GetValidationError()
			out.ValidationOutput = state.GetValidationOutput()
			out.RepairCount = state.GetGenerationAttempt() - 1
			if out.RepairCount < 0 {
				out.RepairCount = 0
			}
		default:
			if state.GetCode() != "" {
				out.Code = wrapLuaTransport(state.GetCode())
			} else if state.GetClarificationQuestion() != "" {
				out.Question = wrapTextTransport(state.GetClarificationQuestion())
			} else if state.GetError() != "" {
				out.Error = state.GetError()
				out.ValidationError = state.GetValidationError()
				out.ValidationOutput = state.GetValidationOutput()
				out.RepairCount = state.GetGenerationAttempt() - 1
				if out.RepairCount < 0 {
					out.RepairCount = 0
				}
			}
		}

		if out.Error != "" && out.Code == "" && out.Question == "" {
			ctx.JSON(http.StatusUnprocessableEntity, out)
			return
		}

		ctx.JSON(http.StatusOK, out)
	}
}

package service

import (
	"fmt"
	"regexp"
	"strings"

	"github.com/yuin/gopher-lua/ast"
	"github.com/yuin/gopher-lua/parse"
)

type LuaChecker struct {
	Errors []string
}

var forbiddenFunctions = map[string]bool{
	"os.execute": true, "os.remove": true, "os.rename": true, "os.tmpname": true,
	"io.popen": true, "io.open": true, "io.input": true, "io.output": true, "io.close": true,
	"loadfile": true, "dofile": true, "load": true, "loadstring": true,
	"debug.getinfo": true, "debug.getlocal": true, "debug.setlocal": true,
	"debug.getupvalue": true, "debug.setupvalue": true, "debug.sethook": true, "debug.gethook": true,
	"package.loadlib": true, "require": true,
}

var jsonPathPattern = regexp.MustCompile(`\$(?:\.[a-zA-Z_]|\[)`)

func (c *LuaChecker) Validate(code string) {
	c.Errors = nil
	code = strings.TrimSpace(code)
	if code == "" {
		c.Errors = append(c.Errors, "Mistake in Line 1: Empty code")
		return
	}

	code = c.checkWrapper(code)
	if len(c.Errors) > 0 {
		return
	}

	c.checkJsonPathPreCheck(code)

	chunk, err := parse.Parse(strings.NewReader(code), "<validation>")
	if err != nil {
		line := 1
		fmt.Sscanf(err.Error(), "line:%d(", &line)
		if line == 1 {
			fmt.Sscanf(err.Error(), ":%d:", &line)
		}
		c.Errors = append(c.Errors, fmt.Sprintf("Mistake in Line %d: Syntax error - %s", line, err.Error()))
		return
	}

	c.walkSlice(chunk)
}

func (c *LuaChecker) checkWrapper(code string) string {
	trimmed := strings.TrimSpace(code)
	if strings.HasPrefix(trimmed, "lua{") && strings.HasSuffix(trimmed, "}lua") {
		return strings.TrimSpace(trimmed[4 : len(trimmed)-4])
	}
	return code
}

func (c *LuaChecker) checkJsonPathPreCheck(code string) {
	lines := strings.Split(code, "\n")
	stripStrings := regexp.MustCompile(`"[^"]*"|'[^']*'|\[\[[\s\S]*?\]\]`)

	for i, line := range lines {
		cleanLine := stripStrings.ReplaceAllString(line, `""`)
		if jsonPathPattern.MatchString(cleanLine) {
			c.Errors = append(c.Errors, fmt.Sprintf("Mistake in Line %d: JsonPath usage ($.) is forbidden. Use direct access via wf.vars", i+1))
		}
	}
}

func (c *LuaChecker) walk(node any) {
	if node == nil {
		return
	}

	line := 0
	if stmt, ok := node.(ast.Stmt); ok {
		line = stmt.Line()
	} else if expr, ok := node.(ast.Expr); ok {
		line = expr.Line()
	}

	switch n := node.(type) {
	case *ast.FuncCallStmt:
		// Извлекаем FuncCallExpr из FuncCallStmt
		if callExpr, ok := n.Expr.(*ast.FuncCallExpr); ok {
			c.checkFuncCall(callExpr, line)
			c.checkArrayUsage(callExpr, line)
			c.walk(callExpr.Func)
			c.walkSliceExprs(callExpr.Args)
		}

	case *ast.LocalAssignStmt:
		c.walkSliceExprs(n.Exprs)

	case *ast.AssignStmt:
		c.walkSliceExprs(n.Lhs)
		c.walkSliceExprs(n.Rhs)

	case *ast.AttrGetExpr:
		c.checkAttrGet(n, line)
		c.walk(n.Object)
		c.walk(n.Key)

	case *ast.TableExpr:
		for _, field := range n.Fields {
			c.walk(field.Key)
			c.walk(field.Value)
		}

	case *ast.IfStmt:
		c.walk(n.Condition)
		c.walkSlice(n.Then)
		c.walkSlice(n.Else)

	case *ast.WhileStmt:
		c.walk(n.Condition)
		c.walkSlice(n.Stmts)

	case *ast.RepeatStmt:
		c.walkSlice(n.Stmts)
		c.walk(n.Condition)

	case *ast.NumberForStmt:
		c.walk(n.Init)
		c.walk(n.Limit)
		if n.Step != nil {
			c.walk(n.Step)
		}
		c.walkSlice(n.Stmts)

	case *ast.GenericForStmt:
		c.walkSliceExprs(n.Exprs)
		c.walkSlice(n.Stmts)

	case *ast.FuncDefStmt:
		c.walkSlice(n.Func.Stmts)

	case *ast.DoBlockStmt:
		c.walkSlice(n.Stmts)

	case *ast.ReturnStmt:
		c.walkSliceExprs(n.Exprs)

	}
}

func (c *LuaChecker) walkSlice(stmts []ast.Stmt) {
	for _, s := range stmts {
		c.walk(s)
	}
}

func (c *LuaChecker) walkSliceExprs(exprs []ast.Expr) {
	for _, e := range exprs {
		c.walk(e)
	}
}

func (c *LuaChecker) checkAttrGet(n *ast.AttrGetExpr, line int) {
	if ident, ok := n.Object.(*ast.IdentExpr); ok && ident.Value == "wf" {
		var keyName string
		if keyStr, ok := n.Key.(*ast.StringExpr); ok {
			keyName = keyStr.Value
		} else if keyIdent, ok := n.Key.(*ast.IdentExpr); ok {
			keyName = keyIdent.Value
		}

		if keyName != "" && keyName != "vars" && keyName != "initVariables" {
			if _, isIdent := n.Key.(*ast.IdentExpr); isIdent {
				c.Errors = append(c.Errors, fmt.Sprintf("Mistake in Line %d: Dynamic access wf[key] is forbidden. Use explicit paths like wf.vars.field", line))
			} else {
				c.Errors = append(c.Errors, fmt.Sprintf("Mistake in Line %d: Invalid access to wf. Allowed: wf.vars or wf.initVariables (found: wf.%s)", line, keyName))
			}
		}
	}
}

func (c *LuaChecker) checkFuncCall(n *ast.FuncCallExpr, line int) {
	funcName := c.getFunctionName(n.Func)
	if forbiddenFunctions[funcName] {
		c.Errors = append(c.Errors, fmt.Sprintf("Mistake in Line %d: Forbidden function call: %s", line, funcName))
	}
}

func (c *LuaChecker) checkArrayUsage(n *ast.FuncCallExpr, line int) {
	funcName := c.getFunctionName(n.Func)

	if funcName == "_utils.array.new" {
		return
	}

	if funcName == "_utils.array.markAsArray" {
		return
	}

	if strings.HasPrefix(funcName, "_utils.array.") &&
		funcName != "_utils.array.new" &&
		funcName != "_utils.array.markAsArray" {
		c.Errors = append(c.Errors, fmt.Sprintf("Mistake in Line %d: Only _utils.array.new() and _utils.array.markAsArray() are allowed for array operations", line))
	}
}

func (c *LuaChecker) getFunctionName(expr ast.Expr) string {
	switch n := expr.(type) {
	case *ast.IdentExpr:
		return n.Value
	case *ast.AttrGetExpr:
		tableName := c.getFunctionName(n.Object)
		var keyName string
		if keyStr, ok := n.Key.(*ast.StringExpr); ok {
			keyName = keyStr.Value
		} else if keyIdent, ok := n.Key.(*ast.IdentExpr); ok {
			keyName = keyIdent.Value
		}
		if tableName != "" && keyName != "" {
			return tableName + "." + keyName
		}
	}
	return "unknown"
}

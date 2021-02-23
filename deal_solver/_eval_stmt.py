# external
import typing
import astroid
import z3

# app
from ._annotations import ann2sort
from ._ast import infer
from ._context import Context, ExceptionInfo, ReturnInfo
from ._eval_expr import eval_expr
from ._exceptions import UnsupportedError
from ._proxies import ProxySort, if_expr, unwrap
from ._registry import HandlersRegistry


eval_stmt = HandlersRegistry()


@eval_stmt.register(astroid.FunctionDef)
def eval_func(node: astroid.FunctionDef, ctx: Context):
    # if it is a recursive call, fake the function
    if node.name in ctx.trace:
        args = [unwrap(v) for v in ctx.scope.layer.values()]
        # generate function signature
        sorts = [arg.sort() for arg in args]
        if not node.returns:
            raise UnsupportedError('no return type annotation for', node.name)
        sorts.append(ann2sort(node.returns, ctx=ctx.z3_ctx))

        func = z3.Function(node.name, *sorts)
        ctx.returns.add(ReturnInfo(
            value=func(*args),
            cond=z3.BoolVal(True, ctx=ctx.z3_ctx)
        ))
        return

    # otherwise, try to execute it
    with ctx.trace.guard(node.name):
        for statement in node.body:
            eval_stmt(node=statement, ctx=ctx)


@eval_stmt.register(astroid.Assert)
def eval_assert(node: astroid.Assert, ctx: Context):
    if node.test is None:
        raise UnsupportedError('assert without condition')
    expr = eval_expr(node=node.test, ctx=ctx)
    if isinstance(expr, ProxySort):
        expr = expr.as_bool
    true = z3.BoolVal(True, ctx=ctx.z3_ctx)
    expr = z3.If(ctx.interrupted, true, expr, ctx=ctx.z3_ctx)
    ctx.expected.add(expr)  # type: ignore


@eval_stmt.register(astroid.Expr)
def eval_expr_stmt(node: astroid.Expr, ctx: Context):
    eval_expr(node=node.value, ctx=ctx)


@eval_stmt.register(astroid.Assign)
def eval_assign(node: astroid.Assign, ctx: Context):
    if not node.targets:
        raise UnsupportedError('assignment to an empty target')
    if len(node.targets) > 1:
        raise UnsupportedError('multiple assignment')
    target = node.targets[0]
    if not isinstance(target, astroid.AssignName):
        raise UnsupportedError('assignment target', type(target))

    value_ref = eval_expr(node=node.value, ctx=ctx)
    ctx.scope.set(name=target.name, value=value_ref)


@eval_stmt.register(astroid.Return)
def eval_return(node: astroid.Return, ctx: Context):
    ctx.returns.add(ReturnInfo(
        value=eval_expr(node=node.value, ctx=ctx),
        cond=z3.Not(ctx.interrupted),
    ))


@eval_stmt.register(astroid.If)
def eval_if_else(node: astroid.If, ctx: Context):
    if node.test is None:
        raise UnsupportedError(type(node))
    if node.body is None:
        raise UnsupportedError(type(node))

    test_ref = eval_expr(node=node.test, ctx=ctx)

    ctx_then = ctx.make_child()
    for subnode in node.body:
        eval_stmt(node=subnode, ctx=ctx_then)
    ctx_else = ctx.make_child()
    for subnode in (node.orelse or []):
        eval_stmt(node=subnode, ctx=ctx_else)

    # update variables
    changed_vars = set(ctx_then.scope.layer) | set(ctx_else.scope.layer)
    for var_name in changed_vars:
        val_then = ctx_then.scope.get(name=var_name)
        val_else = ctx_else.scope.get(name=var_name)
        if val_then is None or val_else is None:
            raise UnsupportedError('unbound variable', var_name)

        value = if_expr(test_ref, val_then, val_else)
        ctx.scope.set(name=var_name, value=value)

    # update new assertions
    true = z3.BoolVal(True, ctx=ctx.z3_ctx)
    for constr in ctx_then.expected.layer:
        ctx.expected.add(if_expr(test_ref, constr, true))
    for constr in ctx_else.expected.layer:
        ctx.expected.add(if_expr(test_ref, true, constr))

    # update new exceptions
    false = z3.BoolVal(False, ctx=ctx.z3_ctx)
    for exc in ctx_then.exceptions.layer:
        ctx.exceptions.add(ExceptionInfo(
            names=exc.names,
            cond=if_expr(test_ref, exc.cond, false),
        ))
    for exc in ctx_else.exceptions.layer:
        ctx.exceptions.add(ExceptionInfo(
            names=exc.names,
            cond=if_expr(test_ref, false, exc.cond),
        ))

    # update new return statements
    false = z3.BoolVal(False, ctx=ctx.z3_ctx)
    for ret in ctx_then.returns.layer:
        ctx.returns.add(ReturnInfo(
            value=ret.value,
            cond=if_expr(test_ref, ret.cond, false),
        ))
    for ret in ctx_else.returns.layer:
        ctx.returns.add(ReturnInfo(
            value=ret.value,
            cond=if_expr(test_ref, false, ret.cond),
        ))


@eval_stmt.register(astroid.Raise)
def eval_raise(node: astroid.Raise, ctx: Context):
    names: typing.Set[str] = set()
    for exc in (node.exc, node.cause):
        if exc is None:
            continue
        names.update(_get_all_bases(exc))
    ctx.exceptions.add(ExceptionInfo(
        names=names,
        cond=z3.Not(ctx.interrupted),
    ))


def _get_all_bases(node) -> typing.Iterator[str]:
    def_nodes = infer(node)
    for def_node in def_nodes:
        if isinstance(def_node, astroid.Instance):
            def_node = def_node._proxied
        if isinstance(node, astroid.Name):
            yield node.name

        if not isinstance(def_node, astroid.ClassDef):
            continue
        yield def_node.name
        for parent_node in def_node.bases:
            if isinstance(parent_node, astroid.Name):
                yield from _get_all_bases(parent_node)


@eval_stmt.register(astroid.Global)
@eval_stmt.register(astroid.ImportFrom)
@eval_stmt.register(astroid.Import)
@eval_stmt.register(astroid.Pass)
def eval_skip(node, ctx: Context):
    pass

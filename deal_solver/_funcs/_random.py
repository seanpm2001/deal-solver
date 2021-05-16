import z3

from .._context import Context
from .._exceptions import UnsupportedError
from .._proxies import ProxySort, random_name, types
from ._registry import register


@register('random.Random.randint')
def random_randint(a, b, ctx: Context, **kwargs):
    result = types.int(z3.Int(random_name('randint')))
    ctx.given.add(result.m_ge(a, ctx=ctx))
    ctx.given.add(result.m_le(b, ctx=ctx))
    return result


@register('random.Random.randrange')
def random_randrange(start, stop, ctx: Context, **kwargs):
    result = types.int(z3.Int(random_name('randrange')))
    ctx.given.add(result.m_ge(start, ctx=ctx))
    ctx.given.add(result.m_lt(stop, ctx=ctx))
    return result


@register('random.Random.choice')
def random_choice(seq, ctx: Context, **kwargs):
    zero = types.int.val(0, ctx=ctx)
    one = types.int.val(1, ctx=ctx)
    if not isinstance(seq, ProxySort):
        raise UnsupportedError("bad argument type for random.choice")
    index = random_randint(
        a=zero,
        b=seq.m_len(ctx=ctx).m_sub(one, ctx=ctx),
        ctx=ctx,
    )
    return seq.m_getitem(index, ctx=ctx)


@register('random.Random.random')
def random_random(ctx: Context, **kwargs):
    zero = types.float.val(0, ctx=ctx)
    one = types.float.val(1, ctx=ctx)
    result = types.float(z3.Const(
        name=random_name('random'),
        sort=types.float.sort(),
    ))
    ctx.given.add(result.m_ge(zero, ctx=ctx))
    ctx.given.add(result.m_le(one, ctx=ctx))
    return result

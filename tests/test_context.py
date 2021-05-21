from deal_solver._context._trace import Trace


def test_trace():
    trace = Trace()
    with trace.guard('one'):
        with trace.guard('two'):
            assert 'one' in trace
            assert 'two' in trace
        assert repr(trace) == 'Trace(one, two)'

import functools
import io
import threading
import unittest
import zipfile

import psutil
import pytest

from iterable_subprocess import iterable_subprocess


def test_cat_not_necessarily_streamed():
    def yield_small_input():
        yield b'first'
        yield b'second'
        yield b'third'

    with iterable_subprocess(['cat'], yield_small_input()) as output:
        assert b''.join(output) == b'firstsecondthird'


def test_cat_streamed():
    latest_input = None

    def yield_input():
        nonlocal latest_input

        for i in range(0, 10000000):
            yield b'*' * 10
            latest_input = i

    with iterable_subprocess(['cat'], yield_input()) as output:
        latest_input_during_output = [latest_input for _ in output]

        # Make sure the input is progressing during the output. In test, there
        # are about 915 steps, so checking that it's greater than 50 shouldm't
        # make this test too flakey
        num_steps = 0
        prev_i = 0
        for i in latest_input_during_output:
            if i != prev_i:
                num_steps += 1
            prev_i = i

        assert num_steps > 50


def test_process_closed_after():
    assert len(psutil.Process().children(recursive=True)) == 0
    with iterable_subprocess(['cat'], ()) as output:
        assert len(psutil.Process().children(recursive=True)) == 1
    assert len(psutil.Process().children(recursive=True)) == 0


def test_exception_from_input_before_yield_propagated():
    def yield_input():
        raise Exception('Something went wrong')

    with pytest.raises(Exception, match='Something went wrong'):
        with iterable_subprocess(['cat'], yield_input()) as output:
            pass


def test_exception_from_input_after_yield_propagated():
    def yield_input():
        yield b'*'
        raise Exception('Something went wrong')

    with pytest.raises(Exception, match='Something went wrong'):
        with iterable_subprocess(['cat'], yield_input()) as output:
            pass


def test_exception_from_input_incorrect_type_propagated():
    def yield_input():
        yield 'this-should-be-bytes'


    with pytest.raises(TypeError):
        with iterable_subprocess(['cat'], yield_input()) as output:
            pass


@pytest.mark.parametrize("size", [
    1, 100, 10000, 1000000,
])
def test_exception_from_output_during_input_iterating_propagates_and_does_not_hang(size):
    event = threading.Event()

    def yield_input():
        for i in range(0, 10000):
            event.set()
            yield b'*' * size

    with pytest.raises(Exception, match='My error'):
        with iterable_subprocess(['cat'], yield_input()) as output:
            event.wait()
            raise Exception('My error')


@pytest.mark.parametrize("chunk_size", [
    1, 100, 10000, 1000000,
])
@pytest.mark.parametrize("at_iteration", [
    0, 1, 100,
])
def test_exception_from_output_iterating_propagates_and_does_not_hang(at_iteration, chunk_size):
    def yield_input():
        for i in range(0, 10000):
            yield b'*' * chunk_size

    with pytest.raises(Exception, match='My error'):
        with iterable_subprocess(['cat'], yield_input(), chunk_size=chunk_size) as output:
            for i, chunk in enumerate(output):
                if i == at_iteration:
                    raise Exception('My error')


def test_exception_from_not_found_process_propagated():
    with pytest.raises(FileNotFoundError):
        with iterable_subprocess(['does-not-exist'], ()) as output:
            b''.join(output)


def test_funzip_no_compression():
    contents = b'*' * 100000

    def yield_input():
        file = io.BytesIO()
        with zipfile.ZipFile(file, 'w', zipfile.ZIP_STORED) as zf:
            zf.writestr('any.txt', contents)

        yield file.getvalue()

    with iterable_subprocess(['funzip'], yield_input()) as output:
        assert b''.join(output) == contents


def test_funzip_deflate():
    contents = b'*' * 100000

    def yield_input():
        file = io.BytesIO()
        with zipfile.ZipFile(file, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('any.txt', contents)

        yield file.getvalue()

    with iterable_subprocess(['funzip'], yield_input()) as output:
        assert b''.join(output) == contents

#!/usr/bin/env python3
"""
HDL Parser, Simulator, and Testing Framework for nand2tetris Final Project.

Usage:
    python hdl_sim.py <chip.hdl> <test_vectors.csv>

Assumptions (per spec):
- HDL syntax is valid.
- Only single-bit inputs/outputs (no buses).
- No sequential chips.
- Non-built-in chips referenced in PARTS exist as .hdls in the same directory.
- Built-ins: Nand, Not, And, Or.
"""

import sys
import os
import re
from typing import Dict, List, Tuple, Optional


# ─── Data Structures ──────────────────────────────────────────────────────────────

class Wire:
    """Represents a wire carrying a boolean value."""
    def __init__(self, name: str):
        self.name = name
        self.value: bool = False

    def __repr__(self):
        return f"Wire({self.name}={int(self.value)})"


class Gate:
    """Base class for logic gates."""
    def evaluate(self) -> None:
        raise NotImplementedError


class NandGate(Gate):
    def __init__(self, in1: Wire, in2: Wire, out: Wire):
        self.in1, self.in2, self.out = in1, in2, out
    def evaluate(self):
        self.out.value = not (self.in1.value and self.in2.value)


class NotGate(Gate):
    def __init__(self, inp: Wire, out: Wire):
        self.inp, self.out = inp, out
    def evaluate(self):
        self.out.value = not self.inp.value


class AndGate(Gate):
    def __init__(self, in1: Wire, in2: Wire, out: Wire):
        self.in1, self.in2, self.out = in1, in2, out
    def evaluate(self):
        self.out.value = self.in1.value and self.in2.value


class OrGate(Gate):
    def __init__(self, in1: Wire, in2: Wire, out: Wire):
        self.in1, self.in2, self.out = in1, in2, out
    def evaluate(self):
        self.out.value = self.in1.value or self.in2.value


BUILTIN_GATES = {
    'Nand': lambda i1, i2, o: NandGate(i1, i2, o),
    'Not':  lambda i,  _, o: NotGate(i, o),      # second input unused
    'And':  lambda i1, i2, o: AndGate(i1, i2, o),
    'Or':   lambda i1, i2, o: OrGate(i1, i2, o),
}


class ChipInstance:
    """A resolved instance of a chip (either built-in or composed)."""
    def __init__(self, chip_type: str, wires: Dict[str, Wire], gates: List[Gate]):
        self.chip_type = chip_type
        self.wires = wires          # all internal + IO wires
        self.gates = gates          # list of gate objects

    def evaluate(self):
        for g in self.gates:
            g.evaluate()


class TopLevelChip:
    """The top-level chip being simulated."""
    def __init__(self, name: str, inputs: List[str], outputs: List[str], instances: List[ChipInstance]):
        self.name = name
        self.input_names = inputs
        self.output_names = outputs
        self.instances = instances
        # Shared wire namespace: every part shares the same pool of named wires
        self.all_wires: Dict[str, Wire] = {}

    def _resolve_wire(self, name: str) -> Wire:
        if name not in self.all_wires:
            self.all_wires[name] = Wire(name)
        return self.all_wires[name]

    def set_input(self, name: str, val: bool):
        w = self._resolve_wire(name)
        w.value = val

    def get_output(self, name: str) -> bool:
        w = self._resolve_wire(name)
        return w.value

    def evaluate(self):
        # Evaluate all sub-chip instances in order
        for inst in self.instances:
            inst.evaluate()


# ─── HDL Parser ───────────────────────────────────────────────────────────────────

def parse_hdl(filepath: str, cache: Dict[str, TopLevelChip]) -> TopLevelChip:
    """Parse an HDL file and return a TopLevelChip description."""
    abs_path = os.path.abspath(filepath)
    if abs_path in cache:
        return cache[abs_path]

    dirname = os.path.dirname(abs_path)
    with open(abs_path, 'r') as f:
        content = f.read()

    # Strip comments (// ... )
    content = re.sub(r'//.*', '', content)

    # Extract chip name
    m_chip = re.search(r'CHIP\s+(\w+)', content)
    assert m_chip, f"No CHIP declaration in {filepath}"
    chip_name = m_chip.group(1)

    # Extract IN section
    m_in = re.search(r'IN\s+\(([^)]+)\)', content)
    input_strs = [x.strip() for x in m_in.group(1).split(',') if x.strip()] if m_in else []

    # Extract OUT section
    m_out = re.search(r'OUT\s+\(([^)]+)\)', content, re.IGNORECASE)
    output_strs = [x.strip() for x in m_out.group(1).split(',') if x.strip()] if m_out else []

    # Extract PARTS section
    parts_block = re.search(r'PARTS\{(.*?)\}', content, re.DOTALL)
    parts_raw = parts_block.group(1) if parts_block else ''

    # Parse each part line
    lines = [l.strip().rstrip(';').strip() for l in parts_raw.split('\n') if l.strip() and not l.strip().startswith('//')]

    parsed_instances = []
    for line in lines:
        if not line:
            continue
        # Format: ChipName(in1=a, in2=b, out=c);
        m_inst = re.match(r'(\w+)\s*\((.*)\)', line)
        if not m_inst:
            continue
        inst_chip = m_inst.group(1)
        args_str = m_inst.group(2)

        # Parse pin assignments: name=value
        pins = {}
        for kv in args_str.split(','):
            kv = kv.strip()
            if '=' in kv:
                k, v = kv.split('=', 1)
                pins[k.strip()] = v.strip()

        parsed_instances.append((inst_chip, pins))

    # Resolve sub-chips recursively
    resolved_instances = []
    for inst_chip, pins in parsed_instances:
        if inst_chip in BUILTIN_GATES:
            # Will be handled during evaluation setup; store descriptor
            resolved_instances.append(('builtin', inst_chip, pins))
        else:
            # Find the .hdl file for this chip
            sub_file = os.path.join(dirname, f"{inst_chip}.hdl")
            sub_chip = parse_hdl(sub_file, cache)
            resolved_instances.append(('composed', sub_chip, pins))

    top = TopLevelChip(chip_name, input_strs, output_strs, [])
    
    # Build actual gate/instance objects wired to shared namespace
    for kind, chip_ref, pins in resolved_instances:
        if kind == 'builtin':
            builder = BUILTIN_GATES[chip_ref]
            # Map pins to wires
            mapped_pins = {k: top._resolve_wire(v) for k, v in pins.items()}
            # For 2-input gates
            if chip_ref in ('Nand', 'And', 'Or'):
                gate = builder(mapped_pins['in1'], mapped_pins['in2'], mapped_pins['out'])
            else:  # Not
                gate = builder(mapped_pins['in'], mapped_pins.get('in2', Wire('_')), mapped_pins['out'])
            dummy_inst = ChipInstance(chip_ref, {}, [gate])
            top.instances.append(dummy_inst)
        else:
            # Composed chip: instantiate its structure into the shared wire space
            sub = chip_ref  # TopLevelChip
            for s_inst_desc in sub.instances:
                # Each sub-instance is already a ChipInstance with gates tied to its own wires.
                # We need to remap those wires to the parent's namespace via the pin mapping.
                pass  # Handled below via direct wiring

            # Actually, simpler approach: inline the sub-chip's gates into parent with remapped wires
            sub_top = chip_ref
            for desc_kind, desc_chip, desc_pins in [(None, None, None)]:  # placeholder
                pass

            # Better: flatten composed chips at parse time
            _flatten_composed(top, sub_top, pins)

    cache[abs_path] = top
    return top


def _flatten_composed(parent: TopLevelChip, sub: TopLevelChip, pin_map: Dict[str, str]):
    """Inline a composed chip's gates into the parent, remapping wires via pin_map."""
    # pin_map maps sub-chip IO names to parent wire names
    # e.g., {'a': 'wireX', 'b': 'wireY', 'out': 'result'}
    wire_mapping = {}
    for sub_io, parent_wire_name in pin_map.items():
        pw = parent._resolve_wire(parent_wire_name)
        wire_mapping[sub_io] = pw

    # Also handle internal wires of sub-chip by creating fresh parent wires
    for inst in sub.instances:
        for gate in inst.gates:
            new_gate = _remap_gate(gate, wire_mapping, parent)
            parent.instances[-1].gates.append(new_gate) if parent.instances else None
            # Create a holder instance if needed
            if not parent.instances:
                parent.instances.append(ChipInstance(f'{sub.name}_inline', {}, []))
            parent.instances[-1].gates.append(new_gate)


def _remap_gate(gate: Gate, wire_map: Dict[str, Wire], parent: TopLevelChip) -> Gate:
    """Create a new gate with wires remapped to parent namespace."""
    def get_or_create(wire: Wire) -> Wire:
        if wire.name in wire_map:
            return wire_map[wire.name]
        # Internal wire: create a new one in parent
        new_name = f"{parent.name}_{wire.name}"
        if new_name not in [w.name for w in parent.all_wires.values()]:
            nw = Wire(new_name)
            parent.all_wires[new_name] = nw
            wire_map[wire.name] = nw
        return parent.all_wires.get(new_name, wire_map[wire.name])

    if isinstance(gate, NandGate):
        i1, i2, o = get_or_create(gate.in1), get_or_create(gate.in2), get_or_create(gate.out)
        return NandGate(i1, i2, o)
    elif isinstance(gate, NotGate):
        i, o = get_or_create(gate.inp), get_or_create(gate.out)
        return NotGate(i, o)
    elif isinstance(gate, AndGate):
        i1, i2, o = get_or_create(gate.in1), get_or_create(gate.in2), get_or_create(gate.out)
        return AndGate(i1, i2, o)
    elif isinstance(gate, OrGate):
        i1, i2, o = get_or_create(gate.in1), get_or_create(gate.in2), get_or_create(gate.out)
        return OrGate(i1, i2, o)
    raise ValueError(f"Unknown gate type: {type(gate)}")


# ─── Simpler Flat Parser (Recommended Approach) ───────────────────────────────────
# The above flattening is tricky. Let's use a cleaner flat-evaluation model:

class FlatSimulator:
    """Flat evaluator: parses everything into a list of gate operations on named wires."""
    
    def __init__(self):
        self.wires: Dict[str, int] = {}  # name -> 0/1
        self.operations: List[Tuple[str, str, str, Optional[str]]] = []  # (gate, in1, in2, out)
        self.cache: Dict[str, list] = {}  # filepath -> ops
    
    def parse_and_load(self, filepath: str):
        abs_p = os.path.abspath(filepath)
        if abs_p in self.cache:
            ops = self.cache[abs_p]
        else:
            ops = self._parse_file(abs_p)
            self.cache[abs_p] = ops
        
        # Apply operations (they may reference other chips, already flattened)
        self.operations.extend(ops)
    
    def _parse_file(self, filepath: str) -> list:
        dirname = os.path.dirname(filepath)
        print(f"Parsing file: {filepath}")
        with open(filepath) as f:
            content = f.read()
        
        content = re.sub(r'//.*', '', content)
        print(content)
        # Get IN/OUT (not strictly needed for flat sim, but good for validation)
        parts_block = re.search(r'PARTS\s*\{(.*?)\}', content, re.DOTALL)
        print(parts_block)
        parts_raw = parts_block.group(1) if parts_block else ''
        
        lines = [l.strip().rstrip(';').strip() for l in parts_raw.split('\n') if l.strip()]
        
        all_ops = []
        for line in lines:
            print(f"Parsing line: {line}")
            m = re.match(r'(\w+)\s*\((.*)\)', line)
            if not m:
                continue
            chip_name = m.group(1)
            args = m.group(2)
            print(f"Found chip: {chip_name} with args: {args}")
            pins = {}
            for kv in args.split(','):
                print(f"Processing pin assignment: {kv}")
                if '=' in kv:
                    k, v = kv.strip().split('=', 1)
                    pins[k.strip()] = v.strip()
            
            if chip_name in BUILTIN_GATES:
                # Direct operation
                if chip_name == 'Not':
                    all_ops.append(('Not', pins['in'], None, pins['out']))
                else:
                    all_ops.append((chip_name, pins['a'], pins['b'], pins['out']))
            else:
                # Recurse
                sub_file = os.path.join(dirname, f"{chip_name}.hdl")
                sub_ops = self._parse_file(sub_file)
                
                # Remap sub_ops pins to current pins
                for op in sub_ops:
                    gate, i1, i2, out = op
                    ni1 = pins.get(i1, i1) if i1 else None
                    ni2 = pins.get(i2, i2) if i2 else None
                    nou = pins.get(out, out)
                    all_ops.append((gate, ni1, ni2, nou))
        
        return all_ops
    
    def set_input(self, name: str, val: bool):
        self.wires[name] = int(val)
    
    def reset_outputs(self, output_names: list):
        for n in output_names:
            self.wires[n] = 0
    
    def evaluate(self):
        for gate, i1, i2, out in self.operations:
            v1 = self.wires.get(i1, 0) if i1 else 0
            v2 = self.wires.get(i2, 0) if i2 else 0
            if gate == 'Nand':
                self.wires[out] = 1 if not (v1 and v2) else 0
            elif gate == 'Not':
                self.wires[out] = 1 if not v1 else 0
            elif gate == 'And':
                self.wires[out] = 1 if (v1 and v2) else 0
            elif gate == 'Or':
                self.wires[out] = 1 if (v1 or v2) else 0
    
    def get_output(self, name: str) -> bool:
        return bool(self.wires.get(name, 0))


# ─── Test Harness ──────────────────────────────────────────────────────────────────

def run_tests(hdl_file: str, csv_file: str):
    sim = FlatSimulator()
    
    # Parse the top-level chip
    sim.parse_and_load(hdl_file)
    print("Operations:", sim.operations) 
    # Read CSV test vectors
    with open(csv_file) as f:
        header_line = f.readline().strip()
        # Format: "a,b; out" or "a,b,c; out1,out2"
        lhs, rhs = header_line.split(';')
        input_names = [x.strip() for x in lhs.split(',')]
        output_names = [x.strip() for x in rhs.split(',')]
        
        total = 0
        passed = 0
        
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            
            # Split into inputs and expected outputs
            vals_part, exp_part = line.split(';')
            input_vals = [int(x.strip()) for x in vals_part.split(',')]
            expected_vals = [int(x.strip()) for x in exp_part.split(',')]
            
            # Set inputs
            for name, val in zip(input_names, input_vals):
                sim.set_input(name, val)
            
            # Reset outputs to avoid carryover
            sim.reset_outputs(output_names)
            
            # Evaluate
            sim.evaluate()
            
            # Check outputs
            actual_vals = [sim.get_output(name) for name in output_names]
            ok = actual_vals == expected_vals
            
            status = "PASS" if ok else "FAIL"
            if ok:
                passed += 1
            
            print(f"[{status}] Inputs: {dict(zip(input_names, input_vals))} | "
                  f"Expected: {expected_vals} | Got: {actual_vals}")
        
        print(f"\n=== Summary: {passed}/{total} tests passed ===")


# ─── Main ──────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python hdl_sim.py <chip.hdl> <test_vectors.csv>")
        sys.exit(1)
    
    hdl_path = sys.argv[1]
    csv_path = sys.argv[2]
    
    if not os.path.exists(hdl_path):
        print(f"Error: HDL file '{hdl_path}' not found.")
        sys.exit(1)
    if not os.path.exists(csv_path):
        print(f"Error: Test vector file '{csv_path}' not found.")
        sys.exit(1)
    
    run_tests(hdl_path, csv_path)

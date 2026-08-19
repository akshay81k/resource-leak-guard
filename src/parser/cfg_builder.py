"""Build a Control-Flow Graph (CFG) from a tree-sitter Java method body.

Phase 2: handles if/else, for/while/do-while, try/catch/finally,
try-with-resources, early return/throw, and structural exception edges.
"""

from __future__ import annotations

from tree_sitter import Node

from src.models import BasicBlock, CFG


class _CFGBuilder:
    """Stateful builder that walks a method body and emits basic blocks."""

    def __init__(self) -> None:
        self._next_id: int = 0
        self._blocks: dict[int, BasicBlock] = {}
        self._exit_ids: set[int] = set()

    def _new_block(self) -> BasicBlock:
        bid = self._next_id
        self._next_id += 1
        block = BasicBlock(id=bid)
        self._blocks[bid] = block
        return block

    def _link(self, src: BasicBlock, dst: BasicBlock) -> None:
        if dst.id not in src.successors:
            src.successors.append(dst.id)
        if src.id not in dst.predecessors:
            dst.predecessors.append(src.id)

    def _get_block_children(self, block_node: Node) -> list[Node]:
        """Get statement children of a block node (skip braces)."""
        return [c for c in block_node.children if c.type not in ("{", "}")]

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def build(self, method_node: Node) -> CFG:
        body = method_node.child_by_field_name("body")
        if body is None:
            entry = self._new_block()
            entry.is_exit = True
            self._exit_ids.add(entry.id)
            return CFG(
                blocks=self._blocks, entry_id=entry.id,
                exit_ids=self._exit_ids, method_node=method_node,
            )

        entry = self._new_block()
        stmts = self._get_block_children(body)
        fall_through = self._process_statements(stmts, entry)

        for block in fall_through:
            block.is_exit = True
            self._exit_ids.add(block.id)

        self._remove_unreachable(entry.id)
        return CFG(
            blocks=self._blocks, entry_id=entry.id,
            exit_ids=self._exit_ids, method_node=method_node,
        )

    def _remove_unreachable(self, entry_id: int) -> None:
        reachable: set[int] = set()
        worklist = [entry_id]
        while worklist:
            bid = worklist.pop()
            if bid in reachable:
                continue
            reachable.add(bid)
            block = self._blocks.get(bid)
            if block:
                worklist.extend(block.successors)
        for bid in set(self._blocks.keys()) - reachable:
            del self._blocks[bid]
            self._exit_ids.discard(bid)

    # ------------------------------------------------------------------
    # Statement dispatcher
    # ------------------------------------------------------------------

    def _process_statements(self, stmts: list[Node], current: BasicBlock) -> list[BasicBlock]:
        """Process a list of statements. Returns fall-through exit blocks."""
        for stmt in stmts:
            if stmt.type in ("{", "}"):
                continue

            if stmt.type == "return_statement":
                current.statements.append(stmt)
                current.is_exit = True
                self._exit_ids.add(current.id)
                return []

            if stmt.type == "throw_statement":
                current.statements.append(stmt)
                current.is_exit = True
                self._exit_ids.add(current.id)
                return []

            if stmt.type == "if_statement":
                exits = self._process_if(stmt, current)
                if not exits:
                    return []
                current = self._new_block()
                for e in exits:
                    self._link(e, current)
                continue

            if stmt.type in ("while_statement", "for_statement",
                             "enhanced_for_statement"):
                exits = self._process_loop(stmt, current)
                if not exits:
                    return []
                current = self._new_block()
                for e in exits:
                    self._link(e, current)
                continue

            if stmt.type == "do_statement":
                exits = self._process_do_while(stmt, current)
                if not exits:
                    return []
                current = self._new_block()
                for e in exits:
                    self._link(e, current)
                continue

            if stmt.type == "try_statement":
                exits = self._process_try(stmt, current)
                if not exits:
                    return []
                current = self._new_block()
                for e in exits:
                    self._link(e, current)
                continue

            if stmt.type == "try_with_resources_statement":
                exits = self._process_try_with_resources(stmt, current)
                if not exits:
                    return []
                current = self._new_block()
                for e in exits:
                    self._link(e, current)
                continue

            # Regular statement — add to current block
            current.statements.append(stmt)

        return [current]

    # ------------------------------------------------------------------
    # if / else
    # ------------------------------------------------------------------

    def _process_if(self, if_node: Node, current: BasicBlock) -> list[BasicBlock]:
        consequence = if_node.child_by_field_name("consequence")
        alternative = if_node.child_by_field_name("alternative")
        exits: list[BasicBlock] = []

        # Then branch
        if consequence:
            then_entry = self._new_block()
            self._link(current, then_entry)
            then_stmts = (self._get_block_children(consequence)
                          if consequence.type == "block" else [consequence])
            exits.extend(self._process_statements(then_stmts, then_entry))

        # Else branch
        if alternative is not None:
            else_entry = self._new_block()
            self._link(current, else_entry)
            if alternative.type == "if_statement":
                exits.extend(self._process_if(alternative, else_entry))
            elif alternative.type == "block":
                exits.extend(self._process_statements(
                    self._get_block_children(alternative), else_entry))
            else:
                exits.extend(self._process_statements([alternative], else_entry))
        else:
            false_exit = self._new_block()
            self._link(current, false_exit)
            exits.append(false_exit)

        return exits

    # ------------------------------------------------------------------
    # while / for / enhanced-for
    # ------------------------------------------------------------------

    def _process_loop(self, loop_node: Node, current: BasicBlock) -> list[BasicBlock]:
        header = self._new_block()
        self._link(current, header)

        body = loop_node.child_by_field_name("body")
        if body is None:
            after = self._new_block()
            self._link(header, after)
            return [after]

        body_entry = self._new_block()
        self._link(header, body_entry)
        body_stmts = (self._get_block_children(body)
                      if body.type == "block" else [body])
        body_exits = self._process_statements(body_stmts, body_entry)

        for eb in body_exits:
            self._link(eb, header)

        after = self._new_block()
        self._link(header, after)
        return [after]

    # ------------------------------------------------------------------
    # do-while
    # ------------------------------------------------------------------

    def _process_do_while(self, do_node: Node, current: BasicBlock) -> list[BasicBlock]:
        body = do_node.child_by_field_name("body")
        body_entry = self._new_block()
        self._link(current, body_entry)

        body_stmts = (self._get_block_children(body)
                      if body and body.type == "block" else ([body] if body else []))
        body_exits = self._process_statements(body_stmts, body_entry)

        cond_block = self._new_block()
        for eb in body_exits:
            self._link(eb, cond_block)
        self._link(cond_block, body_entry)  # back edge

        after = self._new_block()
        self._link(cond_block, after)
        return [after]

    # ------------------------------------------------------------------
    # try / catch / finally
    # ------------------------------------------------------------------

    def _process_try(self, try_node: Node, current: BasicBlock) -> list[BasicBlock]:
        try_body = None
        catch_clauses: list[Node] = []
        finally_clause = None

        for child in try_node.children:
            if child.type == "block" and try_body is None:
                try_body = child
            elif child.type == "catch_clause":
                catch_clauses.append(child)
            elif child.type == "finally_clause":
                finally_clause = child

        if try_body is None:
            return [current]

        # --- finally ---
        finally_entry = None
        finally_exits: list[BasicBlock] = []
        if finally_clause:
            for child in finally_clause.children:
                if child.type == "block":
                    finally_entry = self._new_block()
                    finally_exits = self._process_statements(
                        self._get_block_children(child), finally_entry)
                    break

        # --- catch handlers ---
        catch_entries: list[BasicBlock] = []
        catch_all_exits: list[BasicBlock] = []
        for cc in catch_clauses:
            for child in cc.children:
                if child.type == "block":
                    ce = self._new_block()
                    catch_entries.append(ce)
                    ce_exits = self._process_statements(
                        self._get_block_children(child), ce)
                    if finally_entry:
                        for ex in ce_exits:
                            self._link(ex, finally_entry)
                    else:
                        catch_all_exits.extend(ce_exits)
                    break

        # --- try body ---
        try_entry = self._new_block()
        self._link(current, try_entry)
        try_exits = self._process_statements(
            self._get_block_children(try_body), try_entry)

        # Structural exception edge: try body → first catch
        if catch_entries:
            self._link(try_entry, catch_entries[0])

        # Wire try exits
        if finally_entry:
            for te in try_exits:
                self._link(te, finally_entry)
            return finally_exits
        return try_exits + catch_all_exits

    # ------------------------------------------------------------------
    # try-with-resources
    # ------------------------------------------------------------------

    def _process_try_with_resources(self, twr_node: Node, current: BasicBlock) -> list[BasicBlock]:
        twr_body = None
        catch_clauses: list[Node] = []
        finally_clause = None
        resource_spec = None

        for child in twr_node.children:
            if child.type == "resource_specification":
                resource_spec = child
            elif child.type == "block" and twr_body is None:
                twr_body = child
            elif child.type == "catch_clause":
                catch_clauses.append(child)
            elif child.type == "finally_clause":
                finally_clause = child

        # Add resource specification as a statement so the tracker sees it
        if resource_spec:
            current.statements.append(resource_spec)

        if twr_body is None:
            return [current]

        # --- finally ---
        finally_entry = None
        finally_exits: list[BasicBlock] = []
        if finally_clause:
            for child in finally_clause.children:
                if child.type == "block":
                    finally_entry = self._new_block()
                    finally_exits = self._process_statements(
                        self._get_block_children(child), finally_entry)
                    break

        # --- catch ---
        catch_entries: list[BasicBlock] = []
        catch_all_exits: list[BasicBlock] = []
        for cc in catch_clauses:
            for child in cc.children:
                if child.type == "block":
                    ce = self._new_block()
                    catch_entries.append(ce)
                    ce_exits = self._process_statements(
                        self._get_block_children(child), ce)
                    if finally_entry:
                        for ex in ce_exits:
                            self._link(ex, finally_entry)
                    else:
                        catch_all_exits.extend(ce_exits)
                    break

        # --- body ---
        body_entry = self._new_block()
        self._link(current, body_entry)
        body_exits = self._process_statements(
            self._get_block_children(twr_body), body_entry)

        if catch_entries:
            self._link(body_entry, catch_entries[0])

        if finally_entry:
            for be in body_exits:
                self._link(be, finally_entry)
            return finally_exits
        return body_exits + catch_all_exits


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def build_cfg(method_node: Node) -> CFG:
    """Build a control-flow graph for a single Java method."""
    builder = _CFGBuilder()
    return builder.build(method_node)

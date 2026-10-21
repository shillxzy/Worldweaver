"""Small dependency-graph toolkit used by the consistency engine.

Nodes are hashable keys such as ``("event", 12)`` or ``("character", 3)``.
Edges are directed; undirected relations (friendship, enmity, family...) are stored as
two directed edges and must never be fed to ``topological_sort`` — topological order is
only meaningful for acyclic *temporal / hierarchical* dependency graphs.
"""
from collections import defaultdict, deque


class CycleError(Exception):
    def __init__(self, cycle):
        super().__init__("Graph contains a cycle")
        self.cycle = cycle


class Graph:
    def __init__(self):
        self._out = defaultdict(dict)  # node -> {neighbor: edge_data}
        self._in = defaultdict(dict)
        self._nodes = {}

    # --- construction -----------------------------------------------------
    def add_node(self, node, **data):
        self._nodes.setdefault(node, {}).update(data)
        self._out.setdefault(node, {})
        self._in.setdefault(node, {})

    def add_edge(self, source, target, **data):
        self.add_node(source)
        self.add_node(target)
        self._out[source][target] = data
        self._in[target][source] = data

    def add_undirected_edge(self, a, b, **data):
        self.add_edge(a, b, **data)
        self.add_edge(b, a, **data)

    # --- queries ----------------------------------------------------------
    @property
    def nodes(self):
        return list(self._nodes)

    def node_data(self, node):
        return self._nodes.get(node, {})

    def edges(self):
        for source, targets in self._out.items():
            for target, data in targets.items():
                yield source, target, data

    def edge_data(self, source, target):
        return self._out.get(source, {}).get(target)

    def successors(self, node):
        return list(self._out.get(node, {}))

    def predecessors(self, node):
        return list(self._in.get(node, {}))

    def neighbors(self, node):
        """Adjacent nodes regardless of direction."""
        seen = dict.fromkeys(self.successors(node))
        seen.update(dict.fromkeys(self.predecessors(node)))
        return list(seen)

    def find_path(self, start, goal, directed=True):
        """Shortest path (fewest edges) from start to goal, or None. BFS."""
        if start not in self._nodes or goal not in self._nodes:
            return None
        step = self.successors if directed else self.neighbors
        parents = {start: None}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            if node == goal:
                path = []
                while node is not None:
                    path.append(node)
                    node = parents[node]
                return path[::-1]
            for nxt in step(node):
                if nxt not in parents:
                    parents[nxt] = node
                    queue.append(nxt)
        return None

    def find_cycle(self):
        """Return one directed cycle as a node list ``[a, b, ..., a]`` or None.

        Iterative DFS with white/grey/black colouring (no recursion limit issues).
        """
        white, grey, black = 0, 1, 2
        color = dict.fromkeys(self._nodes, white)
        parent = {}
        for root in self._nodes:
            if color[root] != white:
                continue
            stack = [(root, iter(self.successors(root)))]
            color[root] = grey
            while stack:
                node, it = stack[-1]
                advanced = False
                for nxt in it:
                    if color[nxt] == white:
                        parent[nxt] = node
                        color[nxt] = grey
                        stack.append((nxt, iter(self.successors(nxt))))
                        advanced = True
                        break
                    if color[nxt] == grey:
                        cycle = [nxt, node]
                        cur = node
                        while cur != nxt:
                            cur = parent[cur]
                            cycle.append(cur)
                        return cycle[::-1]
                if not advanced:
                    color[node] = black
                    stack.pop()
        return None

    def topological_sort(self, key=None):
        """Kahn's algorithm. Ties are broken by ``key`` for deterministic output.

        Raises CycleError (with one concrete cycle) if the graph is not a DAG.
        """
        indegree = {node: len(self._in[node]) for node in self._nodes}
        sort_key = key or (lambda n: str(n))
        ready = sorted((n for n, d in indegree.items() if d == 0), key=sort_key)
        order = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            changed = False
            for nxt in self.successors(node):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
                    changed = True
            if changed:
                ready.sort(key=sort_key)
        if len(order) != len(self._nodes):
            raise CycleError(self.find_cycle() or [])
        return order

    def would_create_cycle(self, source, target):
        """True if adding edge source->target would close a directed cycle."""
        if source == target:
            return True
        return self.find_path(target, source) is not None

    def connected_component(self, start):
        if start not in self._nodes:
            return set()
        seen = {start}
        queue = deque([start])
        while queue:
            for nxt in self.neighbors(queue.popleft()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

"""Contains Implementation of GraphAnalyzer class
Provides functionality of analyzing random euclidean graphs.
"""
import math
import logging
import json
from statistics import mean, stdev
from pathlib import Path
from typing import Sequence, Dict, List
from multiprocessing import Pool

from graph_gen import GraphGenerator
from common import *

"""Alias for results type generated by GraphAnalyzer"""
ComponentsSizesSet = Dict[str, Dict[str, List[int]]]


class GraphAnalyzer:

    """Performs analysis on random euclidean graphs
    It uses `GraphGenerator` to generate random euclidean graphs and
    calculates theirs maximum components sizes, probabilities of consistency
    (also means and stddevs). Calculations are also cached in the json file.

    Attributes:
        generator (GraphGenerator): graph generator
        output_dir (Path): directory location for cached results
    """

    generator: GraphGenerator
    output_dir: Path

    def __init__(self, output_dir: Path, generator: GraphGenerator) -> None:
        """Constructor
        Initializes attributes

        Args:
            output_dir (Path): directory location for cached results
            generator (GraphGenerator): graph generator
        """
        assert output_dir.is_dir()
        self.generator = generator
        self.output_dir = output_dir

    @property
    def logger(self) -> logging.Logger:
        """Returns class instance logger

        Returns:
            logging.Logger: instance of class logger
        """
        return logging.getLogger("GraphAnalyzer")

    def __call__(self, sizes: Sequence[int],
                 radiuses: Sequence[float],
                 repeats: int,
                 pool: Pool) -> ResultsSet:
        """Performs analysis of a set of graphs
        For each graph case <`size`,`radius`> it generates random euclidean
        graph (using `GraphGenerator`) and then performs analysis on it.
        Each case will be tested `count` times in parallel using provided pool.
        It means, that for each case sequence of operations goes like below:
            1. <size,radius,0> -> generate(...) -> analyze_one(...)
            2. <size,radius,1> -> generate(...) -> analyze_one(...)
            ...
            #. <size,radius,count> -> generate(...) -> analyze_one(...)

        If some analysis ware performed in the past, results will be re-used.
        Similarly, when got new results, they will be cached in file

        Args:
            sizes (Sequence[int]): sequence of sizes.
                Each one must be greater 0
            radiuses (Sequence[float]): sequence of radiuses.
                Each one must be in range [0.0; 1.0]
            repeats (int): how many test each graph <size,radius> case
            pool (Pool): pool of working processes

        Returns:
            ComponentsSizesSet: maximum component size of each graph case
        """
        assert all([size > 0 for size in sizes])
        assert all([radius >= 0.0 and radius <= 1.0 for radius in radiuses])
        assert repeats >= 0
        self.logger.debug("Performing analysis...")

        comps_sizes_set = self.max_components_sizes(sizes, radiuses,
                                                    repeats, pool)
        return self.post_analysis(comps_sizes_set)

    def max_components_sizes(self, sizes: Sequence[int],
                             radiuses: Sequence[float],
                             repeats: int,
                             pool: Pool) -> ComponentsSizesSet:
        assert all([size > 0 for size in sizes])
        assert all([radius >= 0.0 and radius <= 1.0 for radius in radiuses])
        assert repeats >= 0
        self.logger.debug("Calculating max comps sizes using %s processes...",
                          pool._processes)

        out_comps_sizes_set: ComponentsSizesSet = {}
        comps_sizes_set = self.load_max_comps_sizes()
        modified = False
        try:
            for size in sizes:
                size_str = str(size)
                comps_sizes_subset = comps_sizes_set.setdefault(size_str, {})
                out_comps_sizes_subset = out_comps_sizes_set[size_str] = {}

                for radius in radiuses:
                    radius_str = str(radius)
                    comps_sizes = comps_sizes_subset.setdefault(radius_str, [])
                    if len(comps_sizes) < repeats:
                        # Calculate missing comps_sizes
                        indexes = range(len(comps_sizes), repeats)
                        args = [(size, radius, index) for index in indexes]
                        comps_sizes += pool.starmap(self.analyze_one, args)
                        modified = True

                    out_comps_sizes_subset[radius_str] = comps_sizes[:repeats]
        finally:
            if modified:
                self.save_max_comps_sizes(comps_sizes_set)

        return out_comps_sizes_set

    def post_analysis(self, comps_sizes_set: ComponentsSizesSet) -> ResultsSet:
        results_set: ResultsSet = {}
        for size, comps_sizes_subset in comps_sizes_set.items():
            size_int = int(size)
            results_subset = results_set[size] = {}
            for radius, comps_sizes in comps_sizes_subset.items():
                comps_sizes_mean = mean(comps_sizes)
                comps_sizes_stddev = stdev(comps_sizes)
                consistent_count = 0
                for comp_size in comps_sizes:
                    if comp_size == size_int:
                        consistent_count += 1
                consistency_prob = consistent_count / len(comps_sizes)

                results_subset[radius] = Results(comps_sizes,
                                                 comps_sizes_mean,
                                                 comps_sizes_stddev,
                                                 consistency_prob)
        return results_set

    def analyze_one(self, size: int, radius: float, index: int) -> int:
        """Analyzes one particular graph case.
        It generates graph using GraphGenerator first, and then calculates
        maximum component size for it. It is not caching results nor
        using arleady calculated ones. If it is inteded, use `__call__` method.

        Args:
            size (int): size of graph, must be greater than zero
            radius (float): radius of graph, must be in range [0.0; 1.0]
            index (int): index of graph, must be non-negative

        Returns:
            int: maximum component size for given graph case
        """
        assert size > 0
        assert radius >= 0.0 and radius <= 1.0
        assert index >= 0

        graph = self.generator(size, radius, index)
        self.logger.debug("Calculating maximum component size for "
                          " graph n=%s, r=%s (#%s)...", size, radius, index)
        return graph.max_component_size()

    def load_max_comps_sizes(self) -> ComponentsSizesSet:
        """Reads cached analysis results from the file
        If results could not be loaded, exception will be thrown from
        file reader or json loader.

        Returns:
            ComponentsSizesSet: analysis results
        """
        path = Path.joinpath(self.output_dir, 'max_comps_size.json')
        if not path.is_file():
            self.logger.warn("There is no results cache file: %s", path)
            return {}

        self.logger.debug("Loading cached results from file %s...", path)
        with open(path, "r") as ifile:
            return json.load(ifile)

    def save_max_comps_sizes(self,
                             comps_sizes_set: ComponentsSizesSet) -> None:
        """Writes analysis result to file
        It will be stored in JSON format, in 'output_dir/max_comps_size.json'

        Args:
            comps_sizes_set (ComponentsSizesSet): analysis results
        """
        path = Path.joinpath(self.output_dir, 'max_comps_size.json')
        self.logger.debug("Saving results to file %s...", path)
        with open(path, "w") as ofile:
            return json.dump(comps_sizes_set, ofile)

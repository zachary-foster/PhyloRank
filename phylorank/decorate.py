###############################################################################
#                                                                             #
#    This program is free software: you can redistribute it and/or modify     #
#    it under the terms of the GNU General Public License as published by     #
#    the Free Software Foundation, either version 3 of the License, or        #
#    (at your option) any later version.                                      #
#                                                                             #
#    This program is distributed in the hope that it will be useful,          #
#    but WITHOUT ANY WARRANTY; without even the implied warranty of           #
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the            #
#    GNU General Public License for more details.                             #
#                                                                             #
#    You should have received a copy of the GNU General Public License        #
#    along with this program. If not, see <http://www.gnu.org/licenses/>.     #
#                                                                             #
###############################################################################

import os
import logging
from collections import defaultdict

from phylorank.infer_rank import InferRank
from phylorank.newick import parse_label

from skbio import TreeNode


class Decorate():
    """Decorate nodes with taxonomic ranks inferred from evolutionary divergence."""

    def __init__(self):
        """Initialization."""
        self.logger = logging.getLogger()

        self.rank_prefixes = ['D__', 'P__', 'C__', 'O__', 'F__', 'G__', 'S__', 'ST__']
        self.rank_designators = ['d', 'p', 'c', 'o', 'f', 'g', 's', 'st']
        self.highly_basal_designator = 'X__'

    def run(self, input_tree, output_tree, min_support, only_named_clades, min_length, thresholds):
        """Read distribution file.

        Parameters
        ----------
        input_tree : str
            Name of input tree.
        output_tree : str
            Name of output tree.
        min_support : int
            Only decorate nodes above specified support value.
        only_named_clades : boolean
            Only decorate nodes with existing labels.
        min_length : float
            Only decorate nodes above specified length.
        thresholds : d[rank] -> threshold
            Relative divergence threshold for defining taxonomic ranks.
        """

        # make sure we have a TreeNode object
        root = input_tree
        if not isinstance(root, TreeNode):
            root = TreeNode.read(input_tree, convert_underscores=False)

        # calculate relative distance for all nodes
        infer_rank = InferRank()
        infer_rank.decorate_rel_dist(root)

        # decorate nodes based on specified criteria
        self.logger.info('')
        self.logger.info('  %s\t%s' % ('Rank', 'Prediction results'))

        correct = defaultdict(int)
        incorrect = defaultdict(int)
        for n in root.preorder():
            if n.is_tip():
                continue

            if n.length < min_length:
                continue

            # parse taxon name and support value from node label
            support, taxon_name = parse_label(n.name)

            if support and float(support) < min_support:
                continue

            if only_named_clades and not taxon_name:
                continue

            # Decorate node with predicted rank prefix. Nodes with
            # a relative divergence greater than the genus threshold
            # are a species. Nodes with a relative divergence less than
            # the domain threshold have no real prediction, so are marked
            # with an 'X__', All other nodes will be assigned an intermediate
            # rank based on the threshold values.
            predicted_rank = None
            if n.rel_dist > thresholds['g']:
                predicted_rank = 'S__'
            elif n.rel_dist <= thresholds['d']:
                predicted_rank = self.highly_basal_designator
            else:
                for i in xrange(0, len(thresholds) - 1):
                    parent_threshold = thresholds[self.rank_designators[i]]
                    child_threshold = thresholds[self.rank_designators[i + 1]]
                    if n.rel_dist > parent_threshold and n.rel_dist <= child_threshold:
                        predicted_rank = self.rank_prefixes[i + 1]
                        break

            n.name += '|' + predicted_rank + '[%.2f]' % n.rel_dist
            if predicted_rank != self.highly_basal_designator:
                # tabulate number of correct and incorrect predictions
                named_rank = taxon_name.split(';')[-1][0:3]
                if named_rank == predicted_rank.lower():
                    correct[named_rank] += 1
                else:
                    incorrect[named_rank] += 1

        for rank_prefix in self.rank_prefixes[1:7]:
            correct_taxa = correct[rank_prefix.lower()]
            incorrect_taxa = incorrect[rank_prefix.lower()]
            total_taxa = correct_taxa + incorrect_taxa
            self.logger.info('  %s\t%d of %d (%.2f%%)' % (rank_prefix, correct_taxa, total_taxa, correct_taxa * 100.0 / total_taxa))

        # save decorated tree
        root.write(output_tree)
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
import sys
import logging
from collections import defaultdict, namedtuple

from phylorank.rel_dist import rel_dist_to_named_clades
from phylorank.common import read_taxa_file, filter_taxa_for_dist_inference
from phylorank.newick import parse_label

from skbio import TreeNode

from biolib.taxonomy import Taxonomy
from biolib.plots.abstract_plot import AbstractPlot
from biolib.external.execute import check_dependencies

from numpy import (mean as np_mean,
                   std as np_std,
                   median as np_median,
                   abs as np_abs,
                   array as np_array,
                   arange as np_arange,
                   linspace as np_linspace,
                   percentile as np_percentile)

from scipy.stats import norm

import mpld3


class Outliers(AbstractPlot):
    """Identify outliers based on relative distances.

    A named group is considered an outlier if it falls
    far from the median of all other groups at the same
    rank. Since the relative distance of a group from
    the root depending on the rooting, the input tree
    is rooted on all phyla. Results are reported for
    each of these rooting and a consensus file produced
    indicating the median distance over all rootings.
    """

    def __init__(self):
        """Initialize."""
        self.logger = logging.getLogger()

        Options = namedtuple('Options', 'width height font_size dpi')
        options = Options(6, 6, 12, 96)

        AbstractPlot.__init__(self, options)

        check_dependencies(['genometreetk'])

    def _distribution_plot(self, rel_dists, taxa_for_dist_inference, distribution_table, plot_file):
        """Create plot showing the distribution of taxa at each taxonomic rank.

        Parameters
        ----------
        rel_dists: d[rank_index][taxon] -> relative divergence
            Relative divergence of taxa at each rank.
        taxa_for_dist_inference : iterable
            Taxa to considered when inferring distributions.
        distribution_table : str
            Desired name of output table with distribution information.
        plot_file : str
            Desired name of output plot.
        """

        self.fig.clear()
        self.fig.set_size_inches(12, 6)
        ax = self.fig.add_subplot(111)

        # create normal distributions
        for i, rank in enumerate(sorted(rel_dists.keys())):
            v = [dist for taxa, dist in rel_dists[rank].iteritems() if taxa in taxa_for_dist_inference]
            u = np_mean(v)
            rv = norm(loc=u, scale=np_std(v))
            x = np_linspace(rv.ppf(0.001), rv.ppf(0.999), 1000)
            nd = rv.pdf(x)
            ax.plot(x, 0.75 * (nd / max(nd)) + i, 'b-', alpha=0.6, zorder=2)
            ax.plot((u, u), (i, i + 0.5), 'b-', zorder=2)

        # create percentile and classifciation boundary lines
        percentiles = {}
        for i, rank in enumerate(sorted(rel_dists.keys())):
            v = [dist for taxa, dist in rel_dists[rank].iteritems() if taxa in taxa_for_dist_inference]
            p10, p50, p90 = np_percentile(v, [10, 50, 90])
            ax.plot((p10, p10), (i, i + 0.5), 'r-', zorder=2)
            ax.plot((p50, p50), (i, i + 0.5), 'r-', zorder=2)
            ax.plot((p90, p90), (i, i + 0.5), 'r-', zorder=2)

            for b in [-0.2, -0.1, 0.1, 0.2]:
                boundary = p50 + b
                if boundary < 1.0 and boundary > 0.0:
                    ax.plot((boundary, boundary), (i, i + 0.5), 'g-', zorder=2)

            percentiles[i] = [p10, p50, p90]

        # create scatter plot and results table
        fout = open(distribution_table, 'w')
        fout.write('Taxa\tRelative Distance\tP10\tMedian\tP90\tPercentile outlier\n')
        x = []
        y = []
        c = []
        labels = []
        rank_labels = []
        for i, rank in enumerate(sorted(rel_dists.keys())):
            rank_label = Taxonomy.rank_labels[rank]
            rank_labels.append(rank_label + ' (%d)' % len(rel_dists[rank]))

            for clade_label, dist in rel_dists[rank].iteritems():
                x.append(dist)
                y.append(i)
                labels.append(clade_label)

                if clade_label in taxa_for_dist_inference:
                    c.append((0.0, 0.0, 0.5))
                else:
                    c.append((0.5, 0.5, 0.5))

                p10, p50, p90 = percentiles[i]
                percentile_outlier = not (dist >= p10 and dist <= p90)

                v = [clade_label, dist]
                v += percentiles[i] + [str(percentile_outlier)]
                fout.write('%s\t%.2f\t%.2f\t%.2f\t%.2f\t%s\n' % tuple(v))
        fout.close()

        scatter = ax.scatter(x, y, alpha=0.5, s=48, c=c, zorder=1)

        # set plot elements
        ax.grid(color=(0.8, 0.8, 0.8), linestyle='dashed')

        ax.set_xlabel('relative distance')
        ax.set_xticks(np_arange(0, 1.05, 0.1))
        ax.set_xlim([-0.05, 1.05])

        ax.set_ylabel('rank (no. taxa)')
        ax.set_yticks(xrange(0, len(rel_dists)))
        ax.set_ylim([-0.2, len(rel_dists) - 0.01])
        ax.set_yticklabels(rank_labels)

        self.prettify(ax)

        # make plot interactive
        mpld3.plugins.clear(self.fig)
        mpld3.plugins.connect(self.fig, mpld3.plugins.PointLabelTooltip(scatter, labels=labels))
        mpld3.plugins.connect(self.fig, mpld3.plugins.MousePosition(fontsize=10))
        mpld3.save_html(self.fig, plot_file[0:plot_file.rfind('.')] + '.html')

        self.fig.tight_layout(pad=1)
        self.fig.savefig(plot_file, dpi=96)

    def _median_outlier_file(self, rel_dists, taxa_for_dist_inference, output_file):
        """Identify outliers relative to the median of rank distributions.

        Parameters
        ----------
        rel_dists: d[rank_index][taxon] -> relative divergence
            Relative divergence of taxa at each rank.
        taxa_for_dist_inference : iterable
            Taxa to considered when inferring distributions.
        output_file : str
            Desired name of output table.
        """

        # determine median relative distance for each rank
        median_rel_dist = {}
        for rank, d in rel_dists.iteritems():
            v = [dist for taxa, dist in d.iteritems() if taxa in taxa_for_dist_inference]
            median_rel_dist[rank] = np_median(v)

        fout = open(output_file, 'w')
        fout.write('Taxa\tRelative Distance\tMedian of rank\tDelta distance\tClosest rank\tClassifciation\n')
        for i, rank in enumerate(sorted(rel_dists.keys())):
            for clade_label, dist in rel_dists[rank].iteritems():
                delta = dist - median_rel_dist[rank]

                closest_rank_dist = 1e10
                for test_rank, test_median in median_rel_dist.iteritems():
                    abs_dist = abs(dist - test_median)
                    if abs_dist < closest_rank_dist:
                        closest_rank_dist = abs_dist
                        closest_rank = Taxonomy.rank_labels[test_rank]

                classification = "OK"
                if delta < -0.2:
                    classification = "very overclassified"
                elif delta < -0.1:
                    classification = "overclassified"
                elif delta > 0.2:
                    classification = "very underclassified"
                elif delta > 0.1:
                    classification = "underclassified"

                fout.write('%s\t%.2f\t%.2f\t%.2f\t%s\t%s\n' % (clade_label,
                                                       dist,
                                                       median_rel_dist[rank],
                                                       delta,
                                                       closest_rank,
                                                       classification))
        fout.close()

    def _distribution_summary_plot(self, phylum_rel_dists, taxa_for_dist_inference, distribution_table, plot_file):
        """Summary plot showing the distribution of taxa at each taxonomic rank under different rootings.

        Parameters
        ----------
        phylum_rel_dists: phylum_rel_dists[phylum][rank_index][taxon] -> relative divergences
            Relative divergence of taxon at each rank for different phylum-level rootings.
        taxa_for_dist_inference : iterable
            Taxa to considered when inferring distributions.
        distribution_table : str
            Desired name of output table with distribution information.
        plot_file : str
            Desired name of output plot.
        """

        self.fig.clear()
        self.fig.set_size_inches(12, 6)
        ax = self.fig.add_subplot(111)

        # determine median relative distance for each taxa
        medians_for_taxa = defaultdict(lambda: defaultdict(list))
        for p in phylum_rel_dists:
            for rank, d in phylum_rel_dists[p].iteritems():
                for taxon, dist in d.iteritems():
                    medians_for_taxa[rank][taxon].append(dist)

        # create normal distributions
        for i, rank in enumerate(sorted(medians_for_taxa.keys())):
            v = [np_median(dists) for taxon, dists in medians_for_taxa[rank].iteritems() if taxon in taxa_for_dist_inference]
            u = np_mean(v)
            rv = norm(loc=u, scale=np_std(v))
            x = np_linspace(rv.ppf(0.001), rv.ppf(0.999), 1000)
            nd = rv.pdf(x)
            ax.plot(x, 0.75 * (nd / max(nd)) + i, 'b-', alpha=0.6, zorder=2)
            ax.plot((u, u), (i, i + 0.5), 'b-', zorder=2)

        # create percentile and classification boundary lines
        percentiles = {}
        for i, rank in enumerate(sorted(medians_for_taxa.keys())):
            v = [np_median(dists) for taxon, dists in medians_for_taxa[rank].iteritems() if taxon in taxa_for_dist_inference]
            p10, p50, p90 = np_percentile(v, [10, 50, 90])
            ax.plot((p10, p10), (i, i + 0.5), 'r-', zorder=2)
            ax.plot((p50, p50), (i, i + 0.5), 'r-', zorder=2)
            ax.plot((p90, p90), (i, i + 0.5), 'r-', zorder=2)

            for b in [-0.2, -0.1, 0.1, 0.2]:
                boundary = p50 + b
                if boundary < 1.0 and boundary > 0.0:
                    ax.plot((boundary, boundary), (i, i + 0.5), 'g-', zorder=2)

            percentiles[i] = [p10, p50, p90]

        # create scatter plot and results table
        x = []
        y = []
        c = []
        labels = []
        rank_labels = []
        for i, rank in enumerate(sorted(medians_for_taxa.keys())):
            rank_label = Taxonomy.rank_labels[rank]
            rank_labels.append(rank_label + ' (%d)' % len(medians_for_taxa[rank]))

            for clade_label, dists in medians_for_taxa[rank].iteritems():
                x.append(np_median(dists))
                y.append(i)
                labels.append(clade_label)

                if clade_label in taxa_for_dist_inference:
                    c.append((0.0, 0.0, 0.5))
                else:
                    c.append((0.5, 0.5, 0.5))

        scatter = ax.scatter(x, y, alpha=0.5, s=48, c=c, zorder=1)

        # set plot elements
        ax.grid(color=(0.8, 0.8, 0.8), linestyle='dashed')

        ax.set_xlabel('relative distance')
        ax.set_xticks(np_arange(0, 1.05, 0.1))
        ax.set_xlim([-0.05, 1.05])

        ax.set_ylabel('rank (no. taxa)')
        ax.set_yticks(xrange(0, len(medians_for_taxa)))
        ax.set_ylim([-0.2, len(medians_for_taxa) - 0.01])
        ax.set_yticklabels(rank_labels)

        self.prettify(ax)

        # make plot interactive
        mpld3.plugins.clear(self.fig)
        mpld3.plugins.connect(self.fig, mpld3.plugins.PointLabelTooltip(scatter, labels=labels))
        mpld3.plugins.connect(self.fig, mpld3.plugins.MousePosition(fontsize=10))
        mpld3.save_html(self.fig, plot_file[0:plot_file.rfind('.')] + '.html')

        self.fig.tight_layout(pad=1)
        self.fig.savefig(plot_file, dpi=96)

    def _median_summary_outlier_file(self, phylum_rel_dists,
                                            taxa_for_dist_inference,
                                            gtdb_parent_ranks,
                                            output_file):
        """Identify outliers relative to the median of rank distributions.

        Parameters
        ----------
        phylum_rel_dists: phylum_rel_dists[phylum][rank_index][taxon] -> relative divergences
            Relative divergence of taxon at each rank for different phylum-level rootings.
        taxa_for_dist_inference : iterable
            Taxa to considered when inferring distributions.
        gtdb_parent_ranks: d[taxon] -> string indicating parent taxa
            Parent taxa for each taxon.
        output_file : str
            Desired name of output table.
        """

        # determine median relative distance for each rank abd taxa
        median_for_phyla = defaultdict(list)
        medians_for_taxa = defaultdict(lambda: defaultdict(list))
        dist_per_phyla = defaultdict(lambda: defaultdict(list))
        for p in phylum_rel_dists:
            for rank, d in phylum_rel_dists[p].iteritems():
                v = [dist for taxon, dist in d.iteritems() if taxon in taxa_for_dist_inference]
                phylum_median = np_median(v)
                median_for_phyla[rank].append(phylum_median)

                for taxon, dist in d.iteritems():
                    medians_for_taxa[rank][taxon].append(dist)
                    dist_per_phyla[rank][taxon].append(dist - phylum_median)

        median = {}
        mad = {}
        for r, m in median_for_phyla.iteritems():
            m = np_array(m)
            median[r] = np_median(m)
            mad[r] = np_median(np_abs(m - median[r]))

        fout = open(output_file, 'w')
        fout.write('Taxa\tGTDB taxonomy\tMedian distance\tMedian absolute difference')
        fout.write('\tMedian of rank\tMedian absolute difference\tDistance between medians')
        fout.write('\tClosest rank\tClassifciation\tMean absolute difference\tMean difference\tDistance to rank median\n')
        for rank in sorted(median.keys()):
            for clade_label, dists in medians_for_taxa[rank].iteritems():
                dists = np_array(dists)

                mean_abs_dist = np_mean(np_abs(dist_per_phyla[rank][clade_label]))
                mean_dist = np_mean(dist_per_phyla[rank][clade_label])

                taxon_median = np_median(dists)
                taxon_mad = np_median(np_abs(dists - taxon_median))
                delta = taxon_median - median[rank]

                closest_rank_dist = 1e10
                for test_rank, test_median in median.iteritems():
                    abs_dist = abs(taxon_median - test_median)
                    if abs_dist < closest_rank_dist:
                        closest_rank_dist = abs_dist
                        closest_rank = Taxonomy.rank_labels[test_rank]

                classification = "OK"
                if delta < -0.2:
                    classification = "very overclassified"
                elif delta < -0.1:
                    classification = "overclassified"
                elif delta > 0.2:
                    classification = "very underclassified"
                elif delta > 0.1:
                    classification = "underclassified"

                diff_str = []
                for d in dist_per_phyla[rank][clade_label]:
                    diff_str.append('%.2f' % d)
                diff_str = ', '.join(diff_str)

                fout.write('%s\t%s\t%.2f\t%.3f\t%.2f\t%.3f\t%.3f\t%s\t%s\t%.3f\t%.3f\t%s\n' % (clade_label,
                                                                                           ';'.join(gtdb_parent_ranks[clade_label]),
                                                                                           taxon_median,
                                                                                           taxon_mad,
                                                                                           median[rank],
                                                                                           mad[rank],
                                                                                           delta,
                                                                                           closest_rank,
                                                                                           classification,
                                                                                           mean_abs_dist,
                                                                                           mean_dist,
                                                                                           diff_str))
        fout.close()

    def run(self, input_tree, output_dir, plot_taxa_file, trusted_taxa_file, min_children, min_support):
        """Determine distribution of taxa at each taxonomic rank.

        Parameters
        ----------
        input_tree : str
            Name of input tree.
        output_dir : str
            Desired output directory.
        plot_taxa_file : str
            File specifying taxa to plot. Set to None to consider all taxa.
        trusted_taxa_file : str
            File specifying trusted taxa to consider when inferring distribution. Set to None to consider all taxa.
        min_children : int
            Only consider taxa with at least the specified number of children taxa when inferring distribution.
        min_support : float
            Only consider taxa with at least this level of support when inferring distribution.
        """

        # midpoint root tree
        # midpoint_tree = os.path.join(output_dir, 'midpoint.tree')
        # os.system('genometreetk midpoint %s %s' % (input_tree, midpoint_tree))

        # read tree
        self.logger.info('Reading tree.')
        tree = TreeNode.read(input_tree, convert_underscores=False)

        # pull taxonomy from tree
        taxonomy_file = os.path.join(output_dir, 'taxonomy.tsv')
        taxonomy = Taxonomy().read_from_tree(input_tree)
        Taxonomy().write(taxonomy, taxonomy_file)

        # read taxa to plot
        taxa_to_plot = None
        if plot_taxa_file:
            taxa_to_plot = read_taxa_file(plot_taxa_file)

        # read trusted taxa
        trusted_taxa = None
        if trusted_taxa_file:
            trusted_taxa = read_taxa_file(trusted_taxa_file)

        # determine taxa to be used for inferring distribution
        taxa_for_dist_inference = filter_taxa_for_dist_inference(tree, trusted_taxa, min_children, min_support)

        # calculate relative distance to taxa
        rel_dists = rel_dist_to_named_clades(tree, taxa_to_plot)

        # report number of taxa at each rank
        print ''
        print 'Rank\tTaxa to Plot\tTaxa for Inference'
        for rank, taxa in rel_dists.iteritems():
            taxa_for_inference = [x for x in taxa if x in taxa_for_dist_inference]
            print '%s\t%d\t%d' % (Taxonomy.rank_labels[rank], len(taxa), len(taxa_for_inference))
        print ''

        # get list of phyla level lineages
        phyla = []
        for node in tree.preorder(include_self=False):
            if not node.name or node.is_tip():
                continue

            _support, taxon_name, _auxiliary_info = parse_label(node.name)
            if taxon_name:
                taxa = [x.strip() for x in taxon_name.split(';')]
                if taxa[-1].startswith('p__'):
                    phyla.append(taxa[-1])

        self.logger.info('Identified %d phyla for rooting.' % len(phyla))

        # calculate outliers for tree rooted on each phylum
        phylum_rel_dists = {}
        for p in phyla[0:2]:
            phylum = p.replace('p__', '')
            self.logger.info('Calculating information with rooting on %s.' % phylum)

            phylum_dir = os.path.join(output_dir, phylum)
            if not os.path.exists(phylum_dir):
                os.makedirs(phylum_dir)

            output_tree = os.path.join(phylum_dir, 'rerooted.tree')
            os.system('genometreetk outgroup %s %s %s %s' % (input_tree, taxonomy_file, p, output_tree))

            # calculate relative distance to taxa
            cur_tree = TreeNode.read(output_tree, convert_underscores=False)
            rel_dists = rel_dist_to_named_clades(cur_tree, taxa_to_plot)

            # remove named groups in outgroup
            children = Taxonomy().children(p, taxonomy)
            for r in rel_dists.keys():
                rel_dists[r].pop(p, None)

            for t in children:
                for r in rel_dists.keys():
                    rel_dists[r].pop(t, None)

            phylum_rel_dists[phylum] = rel_dists

            # create distribution plot
            distribution_table = os.path.join(phylum_dir, 'rank_distribution.tsv')
            plot_file = os.path.join(phylum_dir, 'rank_distribution.png')
            self._distribution_plot(rel_dists, taxa_for_dist_inference, distribution_table, plot_file)

            median_outlier_table = os.path.join(phylum_dir, 'median_outlier.tsv')
            self._median_outlier_file(rel_dists, taxa_for_dist_inference, median_outlier_table)

        # distribution_table = os.path.join(output_dir, 'rank_distribution.tsv')
        plot_file = os.path.join(output_dir, 'rank_distribution_summary.png')
        self._distribution_summary_plot(phylum_rel_dists, taxa_for_dist_inference, distribution_table, plot_file)

        gtdb_parent_ranks = Taxonomy().parents(taxonomy)
        median_outlier_table = os.path.join(output_dir, 'median_outlier_summary.tsv')
        self._median_summary_outlier_file(phylum_rel_dists, taxa_for_dist_inference, gtdb_parent_ranks, median_outlier_table)
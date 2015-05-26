#!/usr/bin/env python2
import os
import sys
import time
import cPickle

from numpy		import *
from numpy.random import *
from tssb		 import *
from alleles	 import *
from util		 import *

import numpy.random

from util2 import *
from params import *
from printo import *

import argparse

# num_samples: number of MCMC samples
# mh_itr: number of metropolis-hasting iterations
# rand_seed: random seed (initialization). Set to None to choose random seed automatically.
def start_new_run(state_manager, ssm_file, cnv_file, trees_file, top_k_trees_file, clonal_freqs_file, num_samples, mh_itr, mh_std, rand_seed):
	state = {}
	state['rand_seed'] = rand_seed
	seed(state['rand_seed'])

	state['ssm_file'] = ssm_file
	state['cnv_file'] = cnv_file
	state['trees_file'] = trees_file
	state['top_k_trees_file'] = top_k_trees_file
	state['clonal_freqs_file'] = clonal_freqs_file

	codes, n_ssms, n_cnvs = load_data(state['ssm_file'], state['cnv_file'])
	NTPS = len(codes[0].a) # number of samples / time point
	state['glist'] = [datum.name for datum in codes if len(datum.name)>0]

	# MCMC settings
	state['burnin'] = 1000
	state['num_samples'] = num_samples
	state['dp_alpha'] = 25.0
	state['dp_gamma'] = 1.0
	state['alpha_decay'] = 0.25
	state['top_k'] = 5

	# Metropolis-Hastings settings
	state['mh_burnin'] = 0
	state['mh_itr'] = mh_itr # No. of iterations in metropolis-hastings
	state['mh_std'] = mh_std

	state['cd_llh_traces'] = zeros((state['num_samples'], 1))
	state['working_directory'] = os.getcwd()

	root = alleles(conc=0.1, ntps=NTPS)
	state['tssb'] = TSSB(dp_alpha=state['dp_alpha'], dp_gamma=state['dp_gamma'], alpha_decay=state['alpha_decay'], root_node=root, data=codes)
	# hack...
	if 1:
		depth=0
		state['tssb'].root['sticks'] = vstack([ state['tssb'].root['sticks'], boundbeta(1, state['tssb'].dp_gamma) if depth!=0 else .999])
		state['tssb'].root['children'].append({ 'node': state['tssb'].root['node'].spawn(),
					'main':boundbeta(1.0, (state['tssb'].alpha_decay**(depth+1))*state['tssb'].dp_alpha) if state['tssb'].min_depth <= (depth+1) else 0.0, 
					'sticks' : empty((0,1)),	
					'children' : [] })
		new_node = state['tssb'].root['children'][0]['node']
		for n in range(state['tssb'].num_data):
			state['tssb'].assignments[n].remove_datum(n)
			new_node.add_datum(n)
			state['tssb'].assignments[n] = new_node
	
	for datum in codes:
		datum.tssb = state['tssb']
	
	tree_writer = TreeWriter(trees_file)
	state_manager.write_initial_state(state)
	print("Starting MCMC run...")
	state['last_iteration'] = -state['burnin'] - 1
	do_mcmc(state_manager, state, tree_writer, codes, n_ssms, n_cnvs, NTPS)

def resume_existing_run(state_manager):
	state = state_manager.load_state()
	set_state(state['rand_state'])
	os.chdir(state['working_directory'])
	tree_writer = TreeWriter(state['trees_file'], resume_run=True)

	codes, n_ssms, n_cnvs = load_data(state['ssm_file'], state['cnv_file'])
	NTPS = len(codes[0].a) # number of samples / time point

	do_mcmc(state_manager, state, tree_writer, codes, n_ssms, n_cnvs, NTPS)

def do_mcmc(state_manager, state, tree_writer, codes, n_ssms, n_cnvs, NTPS):
	start_iter = state['last_iteration'] + 1
	for iteration in range(start_iter, state['num_samples']):
		if iteration < 0:
			print iteration

		state['tssb'].resample_assignments()
		state['tssb'].cull_tree()
		
		# assign node ids
		wts, nodes = state['tssb'].get_mixture()
		for i, node in enumerate(nodes):
			node.id = i
		
		##################################################
		## some useful info about the tree,
		## used by CNV related computations,
		## to be called only after resampling assignments
		set_node_height(state['tssb'])
		set_path_from_root_to_node(state['tssb'])
		map_datum_to_node(state['tssb'])
		##################################################

		state['mh_acc'] = metropolis(
			state['tssb'],
			state['mh_itr'],
			state['mh_std'],
			state['mh_burnin'],
			n_ssms,
			n_cnvs,
			state['ssm_file'],
			state['cnv_file'],
			state['rand_seed'],
			NTPS,
		)
		if float(state['mh_acc']) < 0.08 and state['mh_std'] < 10000:
			state['mh_std'] = state['mh_std']*2.0
			print "Shrinking MH proposals. Now %f" % state['mh_std']
		if float(state['mh_acc']) > 0.5 and float(state['mh_acc']) < 0.99:
			state['mh_std'] = state['mh_std']/2.0
			print "Growing MH proposals. Now %f" % state['mh_std']
	
		#root.resample_hypers()
		state['tssb'].resample_sticks()
		state['tssb'].resample_stick_orders()
		state['tssb'].resample_hypers(dp_alpha=True, alpha_decay=True, dp_gamma=True)
 
		if iteration >= 0:
			state['cd_llh_traces'][iteration] = state['tssb'].complete_data_log_likelihood()
			if True or mod(iteration, 10) == 0:
				weights, nodes = state['tssb'].get_mixture()
				print iteration, len(nodes), state['cd_llh_traces'][iteration], state['mh_acc'], state['tssb'].dp_alpha, state['tssb'].dp_gamma, state['tssb'].alpha_decay
			if argmax(state['cd_llh_traces'][:iteration+1]) == iteration:
				print "\t%f is best per-data complete data likelihood so far." % (state['cd_llh_traces'][iteration])

		if iteration >= 0:
			tree_writer.write_tree(state['tssb'], state['cd_llh_traces'][iteration][0], iteration)
		else:
			#tree_writer.write_burnin_tree(state['tssb'], iteration)
			pass
		state['rand_state'] = get_state()
		state['last_iteration'] = iteration
		state_manager.write_state(state)

	#save the best tree
	print_top_trees(state['trees_file'], state['top_k_trees_file'], state['top_k'])

	#save clonal frequencies
	freq = dict([(g,[] )for g in state['glist']])
	glist = array(freq.keys(),str)
	glist.shape=(1,len(glist))
	savetxt(state['clonal_freqs_file'] ,vstack((glist, array([freq[g] for g in freq.keys()]).T)), fmt='%s', delimiter=', ')
	state_manager.delete_state_file()

def test():
	tssb=cPickle.load(open('ptree'))
	wts,nodes=tssb.get_mixture()	
	for dat in tssb.data:
		print [dat.id, dat.__log_likelihood__(0.5)]

if __name__ == "__main__":
	parser = argparse.ArgumentParser(
		description='Run PhyloWGS to infer subclonal composition from SSMs and CNVs',
		formatter_class=argparse.ArgumentDefaultsHelpFormatter
	)
	parser.add_argument('-t', '--trees', dest='trees', default='trees.zip',
		help='Output file where the MCMC trees/samples are saved')
	parser.add_argument('-k', '--top-k-trees', dest='top_k_trees', default='top_k_trees',
		help='Output file to save top-k trees in text format')
	parser.add_argument('-f', '--clonal-freqs', dest='clonal_freqs', default='clonalFrequencies',
		help='Output file to save clonal frequencies')
	parser.add_argument('-s', '--mcmc-samples', dest='mcmc_samples', default=2500, type=int,
		help='Number of MCMC samples')
	parser.add_argument('-i', '--mh-iterations', dest='mh_iterations', default=5000, type=int,
		help='Number of Metropolis-Hastings iterations')
	parser.add_argument('-r', '--random-seed', dest='random_seed', default=1, type=int,
		help='Random seed for initializing MCMC sampler')
	parser.add_argument('ssm_file',
		help='File listing SSMs (simple somatic mutations, i.e., single nucleotide variants. For proper format, see README.md.')
	parser.add_argument('cnv_file',
		help='File listing CNVs (copy number variations). For proper format, see README.md.')
	args = parser.parse_args()

	# Ensure input files exist and can be read.
	try:
		ssm_file = open(args.ssm_file)
		cnv_file = open(args.cnv_file)
		ssm_file.close()
		cnv_file.close()
	except IOError as e:
		print(e)
		sys.exit(1)

	state_manager = StateManager()
	if state_manager.state_exists():
		resume_existing_run(state_manager)
	else:
		start_new_run(
			state_manager,
			args.ssm_file,
			args.cnv_file,
			trees_file=args.trees,
			top_k_trees_file=args.top_k_trees,
			clonal_freqs_file=args.clonal_freqs,
			num_samples=args.mcmc_samples,
			mh_itr=args.mh_iterations,
			mh_std=100,
			rand_seed=args.random_seed
		)

""" mbxaspy main """

from __future__ import print_function

import sys
import os

from utils import *
from defs import *
from init import *
from spectra import *
from analysis import *

# input user-defined arguments from stdin
user_input.read()

# Check initial and final state and perform sanity checks
# Check the initial-state scf calculations
para.sep_line()
para.print(' Checking initial-state scf from: \n ' + user_input.path_i + '\n')
iscf.input(isk = -1)

# Check the final-state scf calculations
para.sep_line()
para.print(' Checking final-state scf from: \n ' + user_input.path_f + '\n')
fscf.input(is_initial = False, isk = -1, nelec = iscf.nelec)

# Important: Need to tell iscf the index of core
if user_input.scf_type == 'shirley_xas':
    iscf.proj.icore = fscf.proj.icore

# Input < B_i | \tilde{B}_j >
fscf.obf.input_overlap(user_input.path_f, iscf.nbnd, fscf.nbnd)

from xi import *
# Compute full atomic overlap sij
if user_input.scf_type == 'shirley_xas': 
    compute_full_sij(fscf.proj)

if not user_input.spec0_only:
    from determinants import *
    spec_xps = []
    spec_xas = []

nspin = iscf.nspin

# initialize the energy axis for spectra
global_ener_axis = spec_class(user_input).ener_axis
if para.isroot(): sp.savetxt('ener_axis.dat', global_ener_axis) # debug
spec0_i = [spec_class(ener_axis = global_ener_axis) for s in range(nspin)]
if user_input.final_1p: spec0_f = [spec_class(ener_axis = global_ener_axis) for s in range(nspin)]
ixyz_list = [-1, 0, 1, 2] # user_input.ixyz_list

## loop over spin and kpoints
for isk in range(pool.nsk):

    ispin, ik  = pool.sk_list[isk] # acquire current spin

    para.sep_line()
    para.print(' Processing (ispin, ik) = ({0},{1}) \n'.format(ispin, ik))

    # weight the sticks according to the k-grid
    weight = iscf.kpt.weight[ik]; 
    prefac = weight * Ryd
    # para.print('weight = {0}'.format(weight)) # debug

    # Import the initial-state scf calculation
    para.sep_line(second_sepl)
    para.print(' Importing initial-state scf\n')
    iscf.input(isk = isk)
    para.print('  xmat: the {0}th atom in ATOMIC_POSITIONS is excited.'.format(xatom(iscf.proj, iscf.xmat) + 1))

    # Import the final-state scf calculation
    para.sep_line(second_sepl)
    para.print(' Importing final-state scf\n', flush = True)
    fscf.input(is_initial = False, isk = isk)
    if user_input.final_1p: para.print('  xmat: the {0}th atom in ATOMIC_POSITIONS card is excited.'.format(xatom(fscf.proj, fscf.xmat) + 1))

    # Obtain the effective occupation number: respect the initial-state #electrons
    if nspin == 1: nocc = iscf.nocc
    else: nocc = iscf.nocc[ik][ispin]

    ## Compute non-interacting spectra *** should I put it in a def ?
    para.print('  Calculating one-body spectra ...\n', flush = True)

    # sticks = xmat_to_sticks(iscf, [-2], nocc, evec = [1.0, 0.0, 0.0]) # debug
    # print(sticks[0]) debug

    # initial-state
    sticks = xmat_to_sticks(iscf, ixyz_list, nocc, offset = -fscf.e_lowest)
    spec0_i[ispin].add_sticks(sticks, user_input, prefac, mode = 'additive')

    # final-state
    if user_input.final_1p:
        sticks = xmat_to_sticks(fscf, ixyz_list, nocc, offset = -fscf.e_lowest)
        spec0_f[ispin].add_sticks(sticks, user_input, prefac, mode = 'additive')
    
    para.print('  One-body spectra finished.')

    ## Compute many-body spectra
    if not user_input.spec0_only:

        para.print('  Calculating many-body spectra ... ')

        ## Compute the transformation matrix xi
        xi = compute_xi(iscf, fscf)

        if user_input.xi_analysis and para.isroot() and ik == 0:
            # plot_xi(xi) # debug
            if nspin > 1:
                msg = eig_analysis_xi(xi, '_spin_{0}'.format(ispin)) # debug
            else:
                msg = eig_analysis_xi(xi) # debug

        ## XPS spectra (N X N)
        para.sep_line(second_sepl)
        para.print('  Calculating many-body XPS spectra ... ')

        Af_list, msg = quick_det(xi[:, 0 : int(nocc)], ener = fscf.obf.eigval,
                                 fix_v1 = False, maxfn = user_input.maxfn - 1,
                                 I_thr = user_input.I_thr,
                                 e_lo_thr = user_input.ELOW, e_hi_thr = user_input.EHIGH, 
                                 comm = pool.comm, 
                                 zeta_analysis = user_input.zeta_analysis and ik == 0)

        first = True
        for order, Af in enumerate(Af_list):

            stick = Af_to_stick(Af)
            ener_axis, spec = stick_to_spectrum(stick, user_input)
            ener_axis += user_input.ESHIFT_FINAL + fscf.obf.eigval[int(nocc)]

            # important information for understanding shakeup effects and convergence 
            para.print("order {0:>2}: no. of sticks = {1:>7}, max stick = {2} ".
                        format( order, len(stick), max([s[1] for s in stick] + [0.0]) ))

            if first:
                spec_xps_ = sp.zeros([len(ener_axis), 2])
                spec_xps_[:, 0] = ener_axis
                first = False

            spec_xps_[:, 1] += spec

        para.print()

        ## XAS spectra ( (N + 1) x (N + 1) )
        para.sep_line(second_sepl)
        para.print('  Calculating many-body XAS spectra ... ')

        first = True
        for ixyz in range(3):

            para.print('  ixyz = {0}'.format(ixyz))
            # Compute xi_c
            xi_c = compute_xi_c(xi, iscf.xmat[:, 0, ixyz], nocc, user_input.nbnd_i)
            # xi_c = compute_xi_c(xi, iscf.xmat[:, 0, ixyz], nocc)
            # para.print('xi_c.shape = {0}'.format(str(xi_c.shape))) # debug

            # Add the last column
            xi_c_ = sp.concatenate((xi[:, 0 : int(nocc)], xi_c), axis = 1)

            Af_list, msg = quick_det(xi_c_, ener = fscf.obf.eigval,
                                     fix_v1 = True, maxfn = user_input.maxfn,
                                     I_thr = user_input.I_thr,
                                     e_lo_thr = user_input.ELOW, e_hi_thr = user_input.EHIGH, 
                                     comm = pool.comm, 
                                     zeta_analysis = user_input.zeta_analysis and ik == 0)

            col = 2 + ixyz

            for order, Af in enumerate(Af_list):

                stick = Af_to_stick(Af)
                ener_axis, spec = stick_to_spectrum(stick, user_input)

                # important information for understanding shakeup effects and convergence 
                para.print("order {0:>2}: no. of sticks = {1:>7}, max stick = {2} ".
                            format( order + 1, len(stick), max([s[1] for s in stick] + [0.0]) ))

                ener_axis += user_input.ESHIFT_FINAL + fscf.obf.eigval[int(nocc)]

                if first:
                    spec_xas_ = sp.zeros([len(ener_axis), 4 + 1])
                    spec_xas_[:, 0] = ener_axis
                    first = False

                spec_xas_[:, col] += spec

            para.print()
        # end of ixyz

        spec_xas_[:, 1] = spec_xas_[:, 2] + spec_xas_[:, 3] + spec_xas_[:, 4]
        spec_xas_[:, 1 : ] *= prefac / 3.0

        # output for debug
        postfix = ''
        postfix += '_ik{0}'.format(ik)
        if nspin == 2:
            postfix += '_ispin{0}'.format(ispin)
        postfix += '.dat'
        
        sp.savetxt(spec_xps_fname + postfix, spec_xps_, delimiter = ' ')
        spec_xps.append(spec_xps_)

        sp.savetxt(spec_xas_fname + postfix, spec_xas_, delimiter = ' ')
        spec_xas.append(spec_xas_)

    # end if spec0_only
# end of isk

## Output Spectra

# intial-state one-body
for ispin in range(nspin): spec0_i[ispin].mp_sum(pool.rootcomm) 

if nspin == 1: spec0_i = spec0_i[0]
else:   spec0_i = spec0_i[0] | spec0_i[1] # mix spin up and down

if para.isroot(): spec0_i.savetxt(spec0_i_fname)

# final-state one-body
if user_input.final_1p:
    for ispin in range(nspin): spec0_f[ispin].mp_sum(pool.rootcomm) 

    if nspin == 1: spec0_f = spec0_f[0]
    else:   spec0_f = spec0_f[0] | spec0_f[1] # mix spin up and down

    if para.isroot(): spec0_f.savetxt(spec0_f_fname)

# spec0_sum = spec0_i[0] + spec0_f[0] # test operator overload
# spec0_sum.savetxt('spec0_sum.dat')

if user_input.spec0_only:
    para.done() # debug

## Calculate total many-body spectra 

# convolute spin-up and -down spectra if nspin == 2
# *** Is this too cumbersome ?
if pool.isroot():

    spec_xas_cvlt = [None] * nspin
    spec_xps_cvlt = [None] * nspin

    pool.log(str(pool.sk_list)) # debug

    first = True
    # go over all the isk th elements
    for isk in range(pool.sk_list_maxl):

        if nspin == 2:
            # find the xps that needs to be sent for the isk tuples overall all pools
            for pool_i_recv, skl in enumerate(pool.sk_list_all):
                # if wanted xps (of opposite spin) is on this pool
                if isk < len(skl): # if skl has the isk th element
                    twin_sk = (1 - skl[isk][0], skl[isk][1]) # find its twin
                    if twin_sk in pool.sk_list:
                        ind = pool.sk_list.index(twin_sk)
                        if pool.rootcomm and pool_i_recv != pool.i:
                            pool.log('xps {0} -> {1}'.format(ind, pool_i_recv)) # debug: watch traffic
                            pool.rootcomm.isend(spec_xps[ind], dest = pool_i_recv)
                        else:
                            spec_xps_twin = spec_xps[ind]
            # receive xps_twin if it is not on the same pool
            if isk < len(pool.sk_list) and (1 - pool.sk_list[isk][0], pool.sk_list[isk][1]) not in pool.sk_list:
                pool.log('received data', flush = True) # debug: watch traffic
                spec_xps_twin = pool.rootcomm.irecv(source = MPI.ANY_SOURCE)

        pool.log(flush = True)

        if isk < len(pool.sk_list):

            # convolute xas with xps_twin
            spec_cvlt = convolute_spec(spec_xas[isk], spec_xps_twin) if nspin == 2 else spec_xas[isk].copy()
            ispin = pool.sk_list[isk][0]
            if first:
                spec_xas_cvlt[ispin] = spec_cvlt
            else:
                spec_xas_cvlt[ispin][:, 1 :: ] += spec_cvlt[:, 1 :: ]

            # convolute xps with xps_twin
            spec_cvlt = convolute_spec(spec_xps[isk], spec_xps_twin) if nspin == 2 else spec_xps[isk].copy()
            if first:
                spec_xps_cvlt[ispin] = spec_cvlt
            else:
                spec_xps_cvlt[ispin][:, 1 :: ] += spec_cvlt[:, 1 :: ]
                first = False

            # *** convolute major sticks (gamma_only)

        if pool.rootcomm: pool.rootcomm.barrier()

    # Add spectra from each k-point
    spec_xas_final = sp.zeros([spec_xas_cvlt[0].shape[0], 4 * nspin + 1])
    spec_xas_final[:, 0] = spec_xas_cvlt[0][:, 0]
    for ispin in range(nspin):
        if pool.rootcomm:
            spec_xas_final[:, 1 + ispin :: nspin] = pool.rootcomm.reduce(spec_xas_cvlt[ispin][:, 1 :: ], op = MPI.SUM)
        if not ismpi():
            spec_xas_final[:, 1 + ispin :: nspin] = spec_xas_cvlt[ispin][:, 1 ::]

    spec_xps_final = sp.zeros([spec_xps_cvlt[0].shape[0], 2])
    spec_xps_final[:, 0] = spec_xps_cvlt[0][:, 0]

    # the two spin channels are the same for xps
    if pool.rootcomm:
        spec_xps_final[:, 1] = pool.rootcomm.reduce(spec_xps_cvlt[ispin][:, 1], op = MPI.SUM)
    if not ismpi():
        spec_xps_final[:, 1] = spec_xps_cvlt[ispin][:, 1]

# This requires the world root is also one of the pool roots: can be made more robust
if para.isroot():
    postfix = '.dat'
    sp.savetxt(spec_xas_fname + postfix, spec_xas_final, delimiter = ' ')
    sp.savetxt(spec_xps_fname + postfix, spec_xps_final, delimiter = ' ')

para.done()
# Bye ! ~

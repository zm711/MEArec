"""
This module group several sub function for recording generator.

All this function work on chunk of signals.
They can be call in loop mode or with joblib.

Important:

When tmp_mode=='memmap' : theses functions must assign and add directly the buffer.
When tmp_mode is Noe : theses functions return the buffer and the assignament is done externally.



"""
import h5py
import numpy as np
import scipy.signal

from MEArec.tools import (filter_analog_signals, convolve_templates_spiketrains,
                          convolve_single_template, convolve_drifting_templates_spiketrains)


class FuncThenAddChunk:
    """
    Helper for functions that do chunk to assign one or several chunks at the 
    good place.
    """

    def __init__(self, func):
        self.func = func

    def __call__(self, *args, **kargs):
        return_dict = self.func(*args)

        ch, i_start, i_stop, = args[:3]
        
        assignement_dict = kargs['assignement_dict']
        tmp_mode = kargs['tmp_mode']

        if tmp_mode is None:
            pass
        elif tmp_mode == 'h5':
            tmp_file = kargs['tmp_file']

            with h5py.File(tmp_file, mode='w') as f:
                for key, full_arr in assignement_dict.items():
                    # full_arr is None in that case
                    out_chunk = return_dict.pop(key)
                    f.create_dataset(key, data=out_chunk)
        elif tmp_mode == 'memmap':
            for key, full_arr in assignement_dict.items():
                out_chunk = return_dict.pop(key)
                if kargs['parallel_job']:
                    # there is a bug in joblib the do no strides in correct way
                    # see https://github.com/joblib/joblib/issues/1019
                    # if joblib fix this then we MUST remove this two lines
                    rev_shape = tuple(full_arr.shape[::-1])
                    full_arr = np.memmap(full_arr.filename, mode='r+', shape=rev_shape,
                                         dtype=full_arr.dtype).transpose()
                full_arr[:, i_start:i_stop] += out_chunk

        return return_dict


def chunk_convolution_(ch, i_start, i_stop, chunk_start,
                       spike_matrix, modulation, drifting, drift_mode, drifting_units, templates,
                       cut_outs_samples, template_locs, velocity_vector, fast_drift_period, fast_drift_min_jump,
                       fast_drift_max_jump, t_start_drift, fs, verbose, amp_mod, bursting_units, shape_mod,
                       shape_stretch, extract_spike_traces, voltage_peaks, dtype, ):
    """
    Perform full convolution for all spike trains by chunk.

    Parameters
    ----------
    ch: int
        Chunk id
    i_start: int
        first index of chunk
    i_stop: 
        last index of chunk (exclude)
    chunk_start: quantity
        Start time for current chunk
    tmp_mearec_file
        temp file:
            None : in memmory return results in out dict
            str = h5 mode put out chunk in tmp h5 file
            dict = memmap mode
    
    spike_matrix: np.array
        2D matrix with binned spike trains
    modulation: str
        Modulation type
    drifting: bool
        If True drifting is performed
    drift_mode :  str
        Drift mode ['slow' | 'fast' | 'slow+fast']
    drifting_units: list
        List of drifting units (if None all units are drifted)
    templates: np.array
        Templates
    cut_outs_samples: list
        List with number of samples to cut out before and after spike peaks
    template_locs: np.array
        For drifting, array with drifting locations
    velocity_vector: np.array
        For drifting, drifring direction
    fast_drift_period : Quantity
        Periods between fast drifts
    fast_drift_min_jump : float
        Min 'jump' in um for fast drifts
    fast_drift_max_jump : float
        Max 'jump' in um for fast drifts
    t_start_drift: quantity
        For drifting, start drift time
    fs: quantity
        Sampling frequency
    verbose: bool
        If True output is verbose
    amp_mod: np.array
        Array with modulation values
    bursting_units : list
        List of bursting units
    shape_mod: bool
        If True waveforms are modulated in shape
    shape_stretch: float
        Low and high frequency for bursting
    extract_spike_traces: bool
        If True (default), spike traces are extracted
    voltage_peaks: np.array
        Array containing the voltage values at the peak
    
    """
    length = i_stop - i_start

    template_idxs = []
    if extract_spike_traces:
        spike_traces = np.zeros((len(spike_matrix), length), dtype=dtype)
    if len(templates.shape) == 4:
        n_elec = templates.shape[2]
    elif len(templates.shape) == 5:
        n_elec = templates.shape[3]
    else:
        raise AttributeError("Wrong 'templates' shape!")

    recordings = np.zeros((n_elec, length), dtype=dtype)

    for st, spike_bin in enumerate(spike_matrix):
        if extract_spike_traces:
            max_electrode = np.argmax(voltage_peaks[st])

        seed = np.random.randint(10000)
        np.random.seed(seed)

        if modulation in ['electrode', 'template']:
            mod_bool = True
            if bursting_units is not None:
                if st in bursting_units and shape_mod:
                    unit_burst = True
                else:
                    unit_burst = False
            else:
                unit_burst = False
            mod_array = amp_mod[st]
        else:  # modulation 'none'
            mod_bool = False
            mod_array = None
            unit_burst = False

        if drifting and st in drifting_units:
            recordings, template_idx = convolve_drifting_templates_spiketrains(st, spike_bin[i_start:i_stop],
                                                                               templates[st],
                                                                               cut_out=cut_outs_samples,
                                                                               modulation=mod_bool,
                                                                               mod_array=mod_array,
                                                                               fs=fs,
                                                                               loc=template_locs[st],
                                                                               drift_mode=drift_mode,
                                                                               slow_drift_velocity=velocity_vector,
                                                                               fast_drift_period=fast_drift_period,
                                                                               fast_drift_min_jump=fast_drift_min_jump,
                                                                               fast_drift_max_jump=fast_drift_max_jump,
                                                                               t_start_drift=t_start_drift,
                                                                               chunk_start=chunk_start,
                                                                               bursting=unit_burst,
                                                                               sigmoid_range=shape_stretch,
                                                                               verbose=verbose,
                                                                               recordings=recordings)
            np.random.seed(seed)
            if extract_spike_traces:
                spike_traces[st] = convolve_single_template(st, spike_bin[i_start:i_stop],
                                                            templates[st, 0, :, max_electrode],
                                                            cut_out=cut_outs_samples,
                                                            modulation=mod_bool,
                                                            mod_array=mod_array,
                                                            bursting=unit_burst,
                                                            sigmoid_range=shape_stretch)
        else:
            if drifting:
                template = templates[st, 0]
            else:
                template = templates[st]
            recordings = convolve_templates_spiketrains(st, spike_bin[i_start:i_stop], template,
                                                        cut_out=cut_outs_samples,
                                                        modulation=mod_bool,
                                                        mod_array=mod_array,
                                                        bursting=unit_burst,
                                                        sigmoid_range=shape_stretch,
                                                        verbose=verbose,
                                                        recordings=recordings)
            np.random.seed(seed)
            if extract_spike_traces:
                spike_traces[st] = convolve_single_template(st, spike_bin[i_start:i_stop],
                                                            template[:, max_electrode],
                                                            cut_out=cut_outs_samples,
                                                            modulation=mod_bool,
                                                            mod_array=mod_array,
                                                            bursting=unit_burst,
                                                            sigmoid_range=shape_stretch)
            template_idx = None
        template_idxs.append(template_idx)

    if verbose:
        print('Done all convolutions for chunk', ch)

    return_dict = dict()
    return_dict['recordings'] = recordings
    if extract_spike_traces:
        return_dict['spike_traces'] = spike_traces
    return_dict['template_idxs'] = template_idxs

    return return_dict


chunk_convolution = FuncThenAddChunk(chunk_convolution_)


def chunk_uncorrelated_noise_(ch, i_start, i_stop, chunk_start,
                              num_chan, noise_level, noise_color, color_peak, color_q, color_noise_floor, fs, dtype):
    length = i_stop - i_start
    additive_noise = noise_level * np.random.randn(num_chan, length).astype(dtype)

    if noise_color:
        # iir peak filter
        b_iir, a_iir = scipy.signal.iirpeak(color_peak, Q=color_q, fs=fs)
        additive_noise = scipy.signal.filtfilt(b_iir, a_iir, additive_noise, axis=1, padlen=1000)
        additive_noise = additive_noise.astype(dtype)
        additive_noise += color_noise_floor * np.std(additive_noise) * \
                          np.random.randn(additive_noise.shape[0], additive_noise.shape[1])
        additive_noise = additive_noise * (noise_level / np.std(additive_noise))

    return_dict = {}
    return_dict['additive_noise'] = additive_noise

    return return_dict


chunk_uncorrelated_noise = FuncThenAddChunk(chunk_uncorrelated_noise_)


def chunk_distance_correlated_noise_(ch, i_start, i_stop, chunk_start,
                                     noise_level, cov_dist, n_elec, noise_color, color_peak, color_q, color_noise_floor,
                                     fs, dtype):
    length = i_stop - i_start

    additive_noise = noise_level * np.random.multivariate_normal(np.zeros(n_elec), cov_dist,
                                                                 size=(length)).astype(dtype).T
    if noise_color:
        # iir peak filter
        b_iir, a_iir = scipy.signal.iirpeak(color_peak, Q=color_q, fs=fs)
        additive_noise = scipy.signal.filtfilt(b_iir, a_iir, additive_noise, axis=1)
        additive_noise = additive_noise + color_noise_floor * np.std(additive_noise) * \
                         np.random.multivariate_normal(np.zeros(n_elec), cov_dist,
                                                       size=(length)).T
    additive_noise = additive_noise * (noise_level / np.std(additive_noise))

    return_dict = {}
    return_dict['additive_noise'] = additive_noise

    return return_dict


chunk_distance_correlated_noise = FuncThenAddChunk(chunk_distance_correlated_noise_)


def chunk_apply_filter_(ch, i_start, i_stop, chunk_start,
                        recordings, cutoff, order, fs, dtype):
    if cutoff.size == 1:
        filtered_chunk = filter_analog_signals(recordings[:, i_start:i_stop], freq=cutoff, fs=fs,
                                               filter_type='highpass', order=order)
    elif cutoff.size == 2:
        if fs / 2. < cutoff[1]:
            filtered_chunk = filter_analog_signals(recordings[:, i_start:i_stop], freq=cutoff[0], fs=fs,
                                                   filter_type='highpass', order=order)
        else:
            filtered_chunk = filter_analog_signals(recordings[:, i_start:i_stop], freq=cutoff, fs=fs)

    filtered_chunk = filtered_chunk.astype(dtype)

    return_dict = {}
    return_dict['filtered_chunk'] = filtered_chunk

    return return_dict


chunk_apply_filter = FuncThenAddChunk(chunk_apply_filter_)

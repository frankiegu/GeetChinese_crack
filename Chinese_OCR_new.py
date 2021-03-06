﻿#! /usr/bin/env python
# -*- coding: utf-8 -*-

import os
import tensorflow.contrib.slim as slim
import time
import logging
import numpy as np
import tensorflow as tf
import pickle
import cv2

logger = logging.getLogger('Training a chinese write char recognition')
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
logger.addHandler(ch)

# 输入参数解析
tf.app.flags.DEFINE_boolean('random_flip_up_down', False, "Whether to random flip up down")
tf.app.flags.DEFINE_boolean('random_brightness', True, "whether to adjust brightness")
tf.app.flags.DEFINE_boolean('random_contrast', True, "whether to random constrast")

tf.app.flags.DEFINE_integer('charset_size', 4000, "Choose the first `charset_size` characters only.")
tf.app.flags.DEFINE_integer('image_size', 64, "Needs to provide same value as in training.")
tf.app.flags.DEFINE_boolean('gray', True, "whether to change the rbg to gray")
tf.app.flags.DEFINE_integer('max_steps', 30002, 'the max training steps ')
tf.app.flags.DEFINE_integer('eval_steps', 10, "the step num to eval")
tf.app.flags.DEFINE_integer('save_steps', 500, "the steps to save")

tf.app.flags.DEFINE_string('chineseorc_checkpoint_dir', './output/chinese/mainimg/', 'the checkpoint dir')
tf.app.flags.DEFINE_string('train_data_dir', './dataset/train/', 'the train dataset dir')
tf.app.flags.DEFINE_string('test_data_dir', './dataset/test/', 'the test dataset dir')
tf.app.flags.DEFINE_string('log_dir', './log', 'the logging dir')
tf.app.flags.DEFINE_string('tfrecord_dir', './dataset/tfrecordtest/', 'the tfrecord dir')
tf.app.flags.DEFINE_boolean('restore', True, 'whether to restore from checkpoint')
tf.app.flags.DEFINE_boolean('epoch', 1, 'Number of epoches')
tf.app.flags.DEFINE_integer('chineseorc_batch_size', 50, 'Validation batch size:128,200')
tf.app.flags.DEFINE_integer('buffer_size', 50000, 'buffer_size:50000 or ')
tf.app.flags.DEFINE_string('mode', 'test', 'Running mode. One of {"train", "valid", "test"}')
#
FLAGS = tf.app.flags.FLAGS


def _parse_record(example_proto):
    features = {
        'name': tf.FixedLenFeature((), tf.string),
        'format': tf.FixedLenFeature((), tf.string),
        'height': tf.FixedLenFeature([], tf.int64),
        'width': tf.FixedLenFeature([], tf.int64),
        'label': tf.FixedLenFeature([], tf.int64),
        'channels': tf.FixedLenFeature([], tf.int64),
        'image_data': tf.FixedLenFeature((), tf.string)}
    features = tf.parse_single_example(example_proto, features=features)
    image = tf.decode_raw(features['image_data'], tf.uint8)
    height = tf.cast(features['height'], tf.int32)
    width = tf.cast(features['width'], tf.int32)
    image = tf.reshape(image, [height, width, 1])
    image = tf.image.resize_images(image,[64,64],method=1)
    label = tf.cast(features['label'], tf.int32)

    return image,label

def build_graph(top_k):
    keep_prob = tf.placeholder(dtype=tf.float32, shape=[], name='keep_prob') # dropout打开概率
    images = tf.placeholder(dtype=tf.float32, shape=[None, 64, 64, 1], name='image_batch')
    labels = tf.placeholder(dtype=tf.int64, shape=[None], name='label_batch')
    is_training = tf.placeholder(dtype=tf.bool, shape=[], name='train_flag')
    with tf.device('/gpu:5'):

        with slim.arg_scope([slim.conv2d, slim.fully_connected],
                            normalizer_fn=slim.batch_norm,
                            normalizer_params={'is_training': is_training}):
            conv3_1 = slim.conv2d(images, 64, [3, 3], 1, padding='SAME', scope='conv3_1')
            max_pool_1 = slim.max_pool2d(conv3_1, [2, 2], [2, 2], padding='SAME', scope='pool1')
            conv3_2 = slim.conv2d(max_pool_1, 128, [3, 3], padding='SAME', scope='conv3_2')
            max_pool_2 = slim.max_pool2d(conv3_2, [2, 2], [2, 2], padding='SAME', scope='pool2')
            conv3_3 = slim.conv2d(max_pool_2, 256, [3, 3], padding='SAME', scope='conv3_3')
            max_pool_3 = slim.max_pool2d(conv3_3, [2, 2], [2, 2], padding='SAME', scope='pool3')
            conv3_4 = slim.conv2d(max_pool_3, 512, [3, 3], padding='SAME', scope='conv3_4')
            conv3_5 = slim.conv2d(conv3_4, 512, [3, 3], padding='SAME', scope='conv3_5')
            max_pool_4 = slim.max_pool2d(conv3_5, [2, 2], [2, 2], padding='SAME', scope='pool4')

            flatten = slim.flatten(max_pool_4)
            fc1 = slim.fully_connected(slim.dropout(flatten, keep_prob), 1024,
                                       activation_fn=tf.nn.relu, scope='fc1')


            logits = slim.fully_connected(slim.dropout(fc1, keep_prob), FLAGS.charset_size, activation_fn=None,
                                          scope='fc2')

        loss = tf.reduce_mean(tf.nn.sparse_softmax_cross_entropy_with_logits(logits=logits, labels=labels))
        accuracy = tf.reduce_mean(tf.cast(tf.equal(tf.argmax(logits, 1), labels), tf.float32))

        global_step = tf.get_variable("step", [], initializer=tf.constant_initializer(0.0), trainable=False)
        optimizer = tf.train.AdamOptimizer(learning_rate=0.1)
        #optimizer = tf.train.GradientDescentOptimizer(learning_rate=0.1)
        train_op = slim.learning.create_train_op(loss, optimizer, global_step=global_step)
        probabilities = tf.nn.softmax(logits)

        # 绘制loss accuracy曲线
        tf.summary.scalar('loss', loss)
        tf.summary.scalar('accuracy', accuracy)
        merged_summary_op = tf.summary.merge_all()
        # 返回top k 个预测结果及其概率；返回top K accuracy
        predicted_val_top_k, predicted_index_top_k = tf.nn.top_k(probabilities, k=top_k)
        accuracy_in_top_k = tf.reduce_mean(tf.cast(tf.nn.in_top_k(probabilities, labels, top_k), tf.float32))

    return {'images': images,
            'labels': labels,
            'keep_prob': keep_prob,
            'top_k': top_k,
            'global_step': global_step,
            'train_op': train_op,
            'loss': loss,
            'is_training': is_training,
            'accuracy': accuracy,
            'accuracy_top_k': accuracy_in_top_k,
            'merged_summary_op': merged_summary_op,
            'predicted_distribution': probabilities,
            'predicted_index_top_k': predicted_index_top_k,
            'predicted_val_top_k': predicted_val_top_k}

def train():
    print('Begin training')

    model_name = 'chinese-rec-model'
    with tf.Session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:

        input_files = [FLAGS.tfrecord_dir + 'trainImg6.tfrecord']
        dataset = tf.contrib.data.TFRecordDataset(input_files)
        dataset = dataset.map(_parse_record)
        shuffle_dataset = dataset.shuffle(buffer_size=FLAGS.buffer_size)
        batch_dataset = shuffle_dataset.batch(FLAGS.chineseorc_batch_size)
        iterator = batch_dataset.make_one_shot_iterator()
        next_element = iterator.get_next()

        graph = build_graph(top_k=1)  # 训练时top k = 1

        saver = tf.train.Saver()
        sess.run(tf.global_variables_initializer())
        # 设置多线程协调器
        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=sess, coord=coord)

        train_writer = tf.summary.FileWriter(FLAGS.log_dir + '/train', sess.graph)
        test_writer = tf.summary.FileWriter(FLAGS.log_dir + '/val')
        start_step = 0
        # 可以从某个step下的模型继续训练
        if FLAGS.restore:
            current_path = os.getcwd()
            #ckpt = os.path.join(model_dir, 'chinese-rec-model-10501')
            ckpt = tf.train.latest_checkpoint(FLAGS.chineseorc_checkpoint_dir)
            if ckpt:
                #saver_restore.restore(sess, ckpt)
                saver.restore(sess, ckpt)
                print("restore from the checkpoint {0}".format(ckpt))
                start_step += int(ckpt.split('-')[-1])
                print(start_step)

        logger.info(':::Training Start:::')
        try:
            i = 0
            while not coord.should_stop():
                i += 1
                print(i)
                start_time = time.time()
                train_images_batch, train_labels_batch = sess.run(next_element)

                feed_dict = {graph['images']: train_images_batch,
                             graph['labels']: train_labels_batch,
                             graph['keep_prob']: 0.8,
                             graph['is_training']: True}
                _, loss_val, train_summary, step = sess.run(
                    [graph['train_op'], graph['loss'], graph['merged_summary_op'], graph['global_step']],
                    feed_dict=feed_dict)
                train_writer.add_summary(train_summary, step)
                end_time = time.time()
                logger.info("the step {0} takes {1} loss {2}".format(step, end_time - start_time, loss_val))
                if step > FLAGS.max_steps:
                    break
                if step % FLAGS.eval_steps == 1:
                    test_images_batch, test_labels_batch = sess.run(next_element)
                    feed_dict = {graph['images']: test_images_batch,
                                 graph['labels']: test_labels_batch,
                                 graph['keep_prob']: 1.0,
                                 graph['is_training']: True}
                    accuracy_test, test_summary = sess.run([graph['accuracy'], graph['merged_summary_op']],
                                                           feed_dict=feed_dict)
                    if step > 300:
                        test_writer.add_summary(test_summary, step)
                    logger.info('===============Eval a batch=======================')
                    logger.info('the step {0} test accuracy: {1}'
                                .format(step, accuracy_test))
                    logger.info('===============Eval a batch=======================')
                if step % FLAGS.save_steps == 1:
                    logger.info('Save the ckpt of {0}'.format(step))
                    saver.save(sess, os.path.join(FLAGS.chineseorc_checkpoint_dir, model_name),
                               global_step=graph['global_step'])
        except tf.errors.OutOfRangeError:
            logger.info('==================Train Finished================')
            saver.save(sess, os.path.join(FLAGS.chineseorc_checkpoint_dir, model_name), global_step=graph['global_step'])
        finally:
            # 达到最大训练迭代数的时候清理关闭线程
            coord.request_stop()
        coord.join(threads)


def validation():
    print('Begin validation')

    final_predict_val = []
    final_predict_index = []
    groundtruth = []

    with tf.Session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:
        input_files = [FLAGS.tfrecord_dir + 'testImg.tfrecord']
        dataset = tf.contrib.data.TFRecordDataset(input_files)
        dataset = dataset.map(_parse_record)
        shuffle_dataset = dataset.shuffle(buffer_size=FLAGS.buffer_size)
        batch_dataset = shuffle_dataset.batch(FLAGS.chineseorc_batch_size)
        iterator = batch_dataset.make_one_shot_iterator()
        next_element = iterator.get_next()


        graph = build_graph(top_k=5)
        saver = tf.train.Saver()

        sess.run(tf.global_variables_initializer())
        sess.run(tf.local_variables_initializer())  # initialize test_feeder's inside state

        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=sess, coord=coord)

        ckpt = tf.train.latest_checkpoint(FLAGS.chineseorc_checkpoint_dir)
        if ckpt:
            saver.restore(sess, ckpt)
            print("restore from the checkpoint {0}".format(ckpt))

        logger.info(':::Start validation:::')
        i = 0
        acc_top_1, acc_top_k = 0.0, 0.0
        try:
            while not coord.should_stop():
                i += 1
                start_time = time.time()
                test_images_batch, test_labels_batch = sess.run(next_element)
                feed_dict = {graph['images']: test_images_batch,
                             graph['labels']: test_labels_batch,
                             graph['keep_prob']: 1.0,
                             graph['is_training']: False}
                batch_labels, probs, indices, acc_1, acc_k = sess.run([graph['labels'],
                                                                       graph['predicted_val_top_k'],
                                                                       graph['predicted_index_top_k'],
                                                                       graph['accuracy'],
                                                                       graph['accuracy_top_k']], feed_dict=feed_dict)
                final_predict_val += probs.tolist()
                final_predict_index += indices.tolist()
                groundtruth += batch_labels.tolist()
                acc_top_1 += acc_1
                acc_top_k += acc_k
                end_time = time.time()
                logger.info("the batch {0} takes {1} seconds, accuracy = {2}(top_1) {3}(top_k)"
                            .format(i, end_time - start_time, acc_1, acc_k))

        except tf.errors.OutOfRangeError:
            logger.info('==================Validation Finished================')
            acc_top_1 = acc_top_1 * FLAGS.chineseorc_batch_size / (i*FLAGS.chineseorc_batch_size+1)
            acc_top_k = acc_top_k * FLAGS.chineseorc_batch_size / (i*FLAGS.chineseorc_batch_size+1)
            logger.info('top 1 accuracy {0} top k accuracy {1}'.format(acc_top_1, acc_top_k))
        finally:
            coord.request_stop()
        coord.join(threads)
    return {'prob': final_predict_val, 'indices': final_predict_index, 'groundtruth': groundtruth}

# 获待预测图像文件夹内的图像名字
def get_file_list_new(path):
    list_name=[]
    names =[]
    for root, sub_folder, name_list in os.walk(path):
        for name in name_list:
            list_name += [os.path.join(root, name)]
            names +=[name]
    return list_name,names

def clear_file_list(path):
    for root, sub_folder, name_list in os.walk(path):
        for name in name_list:
            list_name = os.path.join(root, name)
            list_name = list_name.replace('\\', '/')
            os.remove(list_name)

# 图像二值化，需注意待预测的汉字是黑底白字还是白底黑字
def binary_pic(name_list):
    for image in name_list:
        temp_image = cv2.imread(image)
        #print image
        GrayImage=cv2.cvtColor(temp_image,cv2.COLOR_BGR2GRAY)
        ret,thresh1=cv2.threshold(GrayImage,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
        single_name = image.split('t/')[1]
        #print single_name
        cv2.imwrite('../data/tmp/'+single_name,thresh1)

def get_label_dict():
    f=open('./list.txt','r')
    label_dict = []
    for line in f.readlines():
        line = line.strip('\n')  # 去掉换行符\n
        label = line.split(' ')
        label_dict.append(label)
    f.close()
    label_dict = dict(label_dict)
    return label_dict


def image_preprocessing(image):
    '''
    Applies dataset-specific image pre-processing. Natural image processing
    (mean subtraction) done by default. Room to add custom preprocessing

    Args:
        image (numpy array 2D/3D): image to be processed
    Returns:
        Preprocessed image
    '''

    # Expand image to 4 dimensions (batch, height, width, channels)
    if len(image.shape) == 2:
        image = np.expand_dims(np.expand_dims(image, 0), 3)  # 增加batch和channels
    else:
        image = np.expand_dims(image, 0)  # 增加batch

    return image


def inference(name_list):
    print('inference')
    image_set=[]
    # 对每张图进行尺寸标准化和归一化
    for image in name_list:
        image = cv2.imread(image, cv2.IMREAD_GRAYSCALE)
        image = cv2.resize(image, (64, 64), interpolation=cv2.INTER_CUBIC)
        # ret2, image = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        image = image_preprocessing(image)
        image_set.append(image)

    # allow_soft_placement 如果你指定的设备不存在，允许TF自动分配设备
    with tf.Session(config=tf.ConfigProto(allow_soft_placement=True)) as sess:
        logger.info('========start inference============')
        # images = tf.placeholder(dtype=tf.float32, shape=[None, 64, 64, 1])
        # Pass a shadow label 0. This label will not affect the computation graph.
        graph = build_graph(top_k=3)
        saver = tf.train.Saver()
        # 自动获取最后一次保存的模型
        # ckpt = os.path.join(model_dir, 'chinese-rec-model-10501')
        ckpt = tf.train.latest_checkpoint(FLAGS.chineseorc_checkpoint_dir)
        start_step = 0
        if ckpt:
            saver.restore(sess, ckpt)
            print("restore from the checkpoint {0}".format(ckpt))
            start_step += int(ckpt.split('-')[-1])
            print(start_step)


        val_list=[]
        idx_list=[]
        # 预测每一张图
        for item in image_set:
            temp_image = item
            predict_val, predict_index = sess.run([graph['predicted_val_top_k'], graph['predicted_index_top_k']],
                                              feed_dict={graph['images']: temp_image,
                                                         graph['keep_prob']: 1.0,
                                                         graph['is_training']: False})
            val_list.append(predict_val)
            idx_list.append(predict_index)
    #return predict_val, predict_index
    return val_list,idx_list

def load_chinese_orc_net(chinese_orc_graph,checkpoint_dir):

    with chinese_orc_graph.as_default():
        logger.info('========start inference============')
        graph = build_graph(top_k=3)
        sess = tf.Session(graph=chinese_orc_graph, config=tf.ConfigProto(allow_soft_placement=True))
        saver = tf.train.Saver()
        # 自动获取最后一次保存的模型
        # ckpt = os.path.join(model_dir, 'chinese-rec-model-10501')
        ckpt = tf.train.latest_checkpoint(checkpoint_dir)
        start_step = 0
        if ckpt:
            saver.restore(sess, ckpt)
            print("restore from the checkpoint {0}".format(ckpt))
            start_step += int(ckpt.split('-')[-1])
            print(start_step)

    return sess,graph


def image_orc(geetcode_bbox,sess,graph):
    image_predict_info = []
    val_list = []
    idx_list = []
    # 对每张图进行尺寸标准化和归一化
    for img_info in geetcode_bbox[0]:
        image = img_info[0]
        print(img_info[0])
        image = cv2.imread(image, cv2.IMREAD_GRAYSCALE)
        image = cv2.resize(image, (64, 64), interpolation=cv2.INTER_CUBIC)

        image = image_preprocessing(image)
    # 预测每一张图
        predict_val, predict_index = sess.run([graph['predicted_val_top_k'], graph['predicted_index_top_k']],
                                              feed_dict={graph['images']: image,
                                                         graph['keep_prob']: 1.0,
                                                         graph['is_training']: False})
        val_list.append(predict_val)
        idx_list.append(predict_index)

        image_predict_info.append([img_info,predict_index[0],predict_val[0]])

    return val_list, idx_list,image_predict_info

def run_chinese_orc(sess,graph,geetcode_bbox):
    label_dict = get_label_dict()
    final_predict_val, final_predict_index,image_predict_info = image_orc(geetcode_bbox,sess,graph)
    for i in range(len(final_predict_val)):
        candidate1 = final_predict_index[i][0][0]
        candidate2 = final_predict_index[i][0][1]
        candidate3 = final_predict_index[i][0][2]
        logger.info('[the result info] image: {0} predict: {1} {2} {3}; predict index {4} predict_val {5}'.format(image_predict_info[i][0][0],
           label_dict[str(candidate1)],label_dict[str(candidate2)],label_dict[str(candidate3)],final_predict_index[i],final_predict_val[i]))
    print('=====================OCR RESULT=======================\n')
    return image_predict_info


def main(_):
    print(FLAGS.mode)
    if FLAGS.mode == "train":
        train()
    elif FLAGS.mode == 'validation':
        dct = validation()
        result_file = 'result.dict'
        logger.info('Write result into {0}'.format(result_file))
        with open(result_file, 'wb') as f:
            pickle.dump(dct, f)
        logger.info('Write file ends')
    elif FLAGS.mode == 'test':
        label_dict = get_label_dict()
        name_list,names = get_file_list_new('./data/demo/chinese')
        print(name_list[:30])
        #binary_pic(name_list)
        #tmp_name_list = get_file_list('../data/tmp')
        # 将待预测的图片名字列表送入predict()进行预测，得到预测的结果及其index
        final_predict_val, final_predict_index = inference(name_list)
        final_reco_text =[]  # 存储最后识别出来的文字串
        # 给出top 3预测，candidate1是概率最高的预测
        #label[i] =
        for i in range(len(final_predict_val)):
            candidate1 = final_predict_index[i][0][0]
            candidate2 = final_predict_index[i][0][1]
            candidate3 = final_predict_index[i][0][2]
            print(candidate1,int(candidate1),label_dict[str(candidate1)])
            final_reco_text.append(label_dict[str(candidate1)])
            # print(names[i])
            # print(label_dict[int(label)])
            # logger.info('[the result info] image: {0} {1}predict: {2} {3} {4}; predict index {5} predict_val {6}'.format(names[i],label_dict[int(label)],
            #     label_dict[int(candidate1)],label_dict[int(candidate2)],label_dict[int(candidate3)],final_predict_index[i],final_predict_val[i]))
            logger.info('[the result info] image: {0} predict: {1} {2} {3}; predict index {4} predict_val {5}'.format(names[i],
                label_dict[str(candidate1)],label_dict[str(candidate2)],label_dict[str(candidate3)],final_predict_index[i],final_predict_val[i]))
            # logger.info('[the result info] image: {0} predict: {1} {2} {3}; predict index {4} predict_val {5}'.format(label_dict[int(label)],
            #     label_dict[int(candidate1)],label_dict[int(candidate2)],label_dict[int(candidate3)],final_predict_index[i],final_predict_val[i]))
        print ('=====================OCR RESULT=======================\n')
        # 打印出所有识别出来的结果（取top 1）
        for i in range(len(final_reco_text)):
           print(final_reco_text[i])

if __name__ == "__main__":
    tf.app.run()

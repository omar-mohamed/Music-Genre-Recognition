from __future__ import print_function
import numpy as np
import tensorflow as tf
from six.moves import cPickle as pickle
from matplotlib import pyplot as plt
from sklearn.decomposition import PCA

##################load data#####################
print("Loading data")

all_data = pickle.load(open('dataset_standarized_all_10.pickle', 'rb'))
train_data = all_data['train_dataset']
test_data = all_data['test_dataset']

train_labels = all_data['train_labels']
test_labels = all_data['test_labels']

del all_data

# in case you want to select a portion of the features
# start_index=0
# end_index=87
# train_data=train_data[:,start_index:end_index,:]
# test_data=test_data[:,start_index:end_index,:]


input_width = train_data.shape[1]
input_height = train_data.shape[2]


# vectorize the data
def reformat(dataset):
    dataset = dataset.reshape(
        (-1, input_width * input_height)).astype(np.float32)
    return dataset


train_data = reformat(train_data)
test_data = reformat(test_data)

print("Shape of training set after vectorization:")
print(train_data.shape)

print("Shape of test set after vectorization:")
print(test_data.shape)

################## PCA #####################

print("Running PCA")

# run pca to reduce vector size to 900
pca = PCA(copy=True, iterated_power='auto', n_components=900, random_state=None,
          svd_solver='auto', tol=0.0, whiten=False)

pca.fit(train_data)

train_data = pca.transform(train_data)

test_data = pca.transform(test_data)

print("Shape of training set after pca:")
print(train_data.shape)

print("Shape of test set after pca:")
print(test_data.shape)

test_size = test_data.shape[0]
train_size = train_data.shape[0]
vector_size = train_data.shape[1]


########################Training Graph###########################

# computes accuracy given the predictions and real labels
def accuracy(predictions, labels):
    batch_size = predictions.shape[0]
    sum = np.sum(predictions == labels)
    acc = (100.0 * sum) / batch_size
    return acc


genres_labels = 10  # the labels' length for a genres classifier
batch_size = 64  # the number of training samples in a single iteration
test_batch_size = 50  # used to calculate test predictions over many iterations to avoid memory issues

num_hidden1 = vector_size  # the size of the unrolled vector
num_hidden2 = 64  # the size of the hidden neurons in hidden layer

regularization_lambda = 4e-1  # used in case of L2 regularization

# initializing tensorflow graph
print("Initializing Tensorflow graph")

graph = tf.Graph()
with graph.as_default():
    # Input data.
    tf_train_dataset = tf.placeholder(
        tf.float32, shape=(batch_size, vector_size), name="train_dataset")

    # labels
    tf_train_labels = tf.placeholder(tf.int32, shape=(batch_size), name="train_labels")

    # test data.
    tf_test_dataset = tf.placeholder(tf.float32, shape=(test_batch_size, vector_size), name="test_set")

    # to take one sample and classify it
    tf_one_input = tf.placeholder(tf.float32, shape=(1, vector_size), name='one_input_placeholder')


    def get_bias_variable(name, shape):
        return tf.Variable(tf.constant(1.0, shape=shape), name=name)


    def get_fully_connected_weight(name, shape):
        weights = tf.get_variable(name, shape=shape,
                                  initializer=tf.contrib.layers.xavier_initializer())
        return weights


    # hidden weights

    hidden1_weights_c1 = get_fully_connected_weight('hidden1_weights', [num_hidden1, num_hidden2])

    hidden2_weights_c1 = get_fully_connected_weight('hidden2_weights', [num_hidden2, genres_labels])


    # method that runs one hidden layer with batch normalization and dropout
    def run_hidden_layer(x, hidden_weights, keep_dropout_rate=1, use_relu=True, is_training=False):
        hidden = tf.matmul(x, hidden_weights)

        hidden = tf.layers.batch_normalization(
            inputs=hidden,
            axis=-1,
            momentum=0.99,
            epsilon=0.001,
            center=True,
            scale=True,
            training=is_training
        )

        if use_relu:
            hidden = tf.nn.leaky_relu(hidden, 0.2)
        if keep_dropout_rate < 1:
            hidden = tf.nn.dropout(hidden, keep_dropout_rate)

        return hidden


    # Model.
    def model(data, keep_dropout_rate=1, is_training=False):
        hidden = data

        hidden = run_hidden_layer(hidden, hidden1_weights_c1, keep_dropout_rate, True, is_training)

        hidden = run_hidden_layer(hidden, hidden2_weights_c1, 1, False, is_training)

        return hidden


    # Training computation.
    logits = model(tf_train_dataset, 0.7, True)

    regularizers = 0  # regularization_lambda*(tf.nn.l2_loss(hidden1_weights_c1) + tf.nn.l2_loss(hidden1_biases_c1))+regularization_lambda*(tf.nn.l2_loss(hidden2_weights_c1) + tf.nn.l2_loss(hidden2_biases_c1))+regularization_lambda*(tf.nn.l2_loss(hidden3_weights_c1) + tf.nn.l2_loss(hidden3_biases_c1))

    # loss using cross entropy on softmax
    loss = tf.reduce_mean(
        tf.nn.sparse_softmax_cross_entropy_with_logits(labels=tf_train_labels, logits=logits)) + regularizers

    # to save batch normalizaiton data
    update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
    with tf.control_dependencies(update_ops):
        # learning rate decay

        # tf.train.exponential_decay(learning_rate, global_step, decay_steps, decay_rate, staircase=False, name=None)
        # decayed_learning_rate = learning_rate *decay_rate ^ (global_step / decay_steps)
        global_step = tf.Variable(0)
        learning_rate = tf.train.exponential_decay(0.0001, global_step, 20000, 0.90, staircase=True)

        # Optimizer.
        optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
        tvars = tf.trainable_variables()
        grads, _ = tf.clip_by_global_norm(tf.gradients(loss, tvars),
                                          100.0)  # gradient clipping
        optimize = optimizer.apply_gradients(
            zip(grads, tvars),
            global_step=global_step)

    # Predictions for the training and test data.

    train_prediction = tf.nn.softmax(logits)

    test_prediction = tf.nn.softmax(model(tf_test_dataset))

    one_prediction = tf.nn.softmax(model(tf_one_input))
    one_prediction = tf.identity(one_prediction, name="one_prediction")


########################Training Session###########################


num_steps = 6000  # number of training iterations

# used for drawing error and accuracy over time
training_loss = []
training_loss_epoch = []

train_accuracy = []
train_accuracy_epoch = []

test_accuracy = 0

print("Training Neural Network")

with tf.Session(graph=graph, config=tf.ConfigProto(log_device_placement=True)) as session:
    tf.global_variables_initializer().run()
    # to save model after finishing
    saver = tf.train.Saver()
    # `sess.graph` provides access to the graph used in a `tf.Session`.
    writer = tf.summary.FileWriter('./graph_info', session.graph)

    print('Initialized')
    for step in range(num_steps):
        offset = (step * batch_size) % (train_size - batch_size)

        batch_data = train_data[offset:(offset + batch_size), :]
        batch_labels = train_labels[offset:(offset + batch_size)]

        # train on batch and get accuracy and loss
        feed_dict = {tf_train_dataset: batch_data, tf_train_labels: batch_labels}
        _, l, predictions, lr = session.run(
            [optimize, loss, train_prediction, learning_rate], feed_dict=feed_dict)

        if (step % 50 == 0):
            print('Learning rate at step %d: %.14f' % (step, lr))
            print('Minibatch loss at step %d: %f' % (step, l))
            batch_train_accuracy = accuracy(np.argmax(predictions, axis=1), batch_labels)
            print('Minibatch accuracy: %.1f%%' % batch_train_accuracy)
            training_loss.append(l)
            training_loss_epoch.append(step)
            train_accuracy.append(batch_train_accuracy)
            train_accuracy_epoch.append(step)
            if (lr == 0):  # if learning rate reaches 0 break
                break

    # get test predictions in steps to avoid memory problems

    test_pred = np.zeros((test_size, genres_labels))

    for step in range(int(test_size / test_batch_size)):
        offset = (step * test_batch_size) % (test_size - test_batch_size)
        batch_data = test_data[offset:(offset + test_batch_size), :]
        feed_dict = {tf_test_dataset: batch_data}
        predictions = session.run(
            test_prediction, feed_dict=feed_dict)

        test_pred[offset:offset + test_batch_size, :] = predictions

    # calculate test accuracy and save the model

    test_accuracy = accuracy(np.argmax(test_pred, axis=1), test_labels)
    writer.close()
    saver.save(session, "./saved_model/model.ckpt")


###############################Plot Results and save images##############################

# saves accuracy and loss images in folder output_images
def plot_x_y(x, y, figure_name, x_axis_name, y_axis_name, ylim=[0, 100]):
    plt.figure()
    plt.plot(x, y)
    plt.xlabel(x_axis_name)
    plt.ylabel(y_axis_name)
    axes = plt.gca()
    axes.set_ylim(ylim)
    # plt.legend([line_name],loc='upper left')
    plt.savefig('./output_images/' + figure_name)
    # plt.show()


plot_x_y(training_loss_epoch, training_loss, 'training_loss.png', 'epoch', 'training batch loss', [0, 15])

plot_x_y(train_accuracy_epoch, train_accuracy, 'training_acc.png', 'epoch', 'training batch accuracy')

print('Test accuracy: %.1f%%' % test_accuracy)

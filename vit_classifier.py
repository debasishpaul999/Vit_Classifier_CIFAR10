# installing neccessary libraries or updating them
!pip install tensorflow_addons
!pip install tensorflow
!pip install keras
!pip install layers

# importing libraries
from keras import backend
import numpy as np
import tensorflow as tf
from tensorflow import keras
import tensorflow_addons as tfa
from tensorflow.keras import layers

# checking for a gpu
import tensorflow as tf
device_name = tf.test.gpu_device_name()
if device_name != '/device:GPU:0':
  raise SystemError('GPU not found')
print('GPU found at: {}'.format(device_name))

num_classes = 10
input_shape = (32,32,3)

(x_train,y_train),(x_test,y_test) = keras.datasets.cifar10.load_data()
print(f"X_train: {x_train.shape} - Y_train: {y_train.shape}")
print(f"X_test: {x_test.shape} - Y_test: {y_test.shape}")

learning_rate = 0.001 # specifis the step size(smaller the learing rate higher accuracy)
weight_decay = 0.0001
batch_size = 256
num_epochs = 600
image_size = 72 # resize the input image
patch_size = 6 # size of patches to be extracted from input target
num_patches = (image_size // patch_size) **2
projection_dim = 64
num_heads = 4
transformer_units = [
    projection_dim*2,
    projection_dim
] # size of the projection layer
transformer_layers = 8
mlp_head_units = [2048,1024] # size of the dense layer of the final classifier

data_augmentation = keras.Sequential(
    [
        layers.Normalization(),
        layers.Resizing(image_size,image_size),
        layers.RandomFlip("horizontal"),
        layers.RandomRotation(factor=0.02),
        layers.RandomZoom(height_factor = 0.2,width_factor = 0.2)
    ],
    name = "data_augmetation"
)
data_augmentation.layers[0].adapt(x_train)

def mlp(x,hidden_units,dropout_rate):
  for units in hidden_units:
    x = layers.Dense(units,activation = tf.nn.gelu)(x)
    x = layers.Dropout(dropout_rate)(x)
  return x

class Patches(layers.Layer):
  def __init__(self,patch_size):
    super(Patches,self).__init__()
    self.patch_size = patch_size

  def call(self,images):
    batch_size = tf.shape(images)[0]
    patches = tf.image.extract_patches(
        images = images,
        sizes = [1,self.patch_size,self.patch_size,1],
        strides = [1,self.patch_size,self.patch_size,1],
        rates = [1,1,1,1],
        padding = "VALID",
    )

    patch_dims = patches.shape[-1]
    patches = tf.reshape(patches,[batch_size,-1,patch_dims])
    return patches

import matplotlib.pyplot as plt

plt.figure(figsize=(4,4))
image = x_train[np.random.choice(range(x_train.shape[0]))]
plt.imshow(image.astype("uint8"))
plt.axis("off")

resized_image = tf.image.resize(
    tf.convert_to_tensor([image]),size=(image_size,image_size)
    )
patches = Patches(patch_size)(resized_image)
print(f"Image size: {image_size} X {image_size}")
print(f"Patch size: {patch_size} X {patch_size}")
print(f"Patches per image: {patches.shape[1]}")
print(f"Elements per patch: {patches.shape[-1]}")

n = int(np.sqrt(patches.shape[1]))
plt.figure(figsize=(4,4))
for i,patch in enumerate(patches[0]):
  ax = plt.subplot(n,n,i+1)
  patch_img = tf.reshape(patch,(patch_size,patch_size,3))
  plt.imshow(patch_img.numpy().astype("uint8"))
  plt.axis("off")

class PatchEncoder(layers.Layer):
  def __init__(self,num_patches,projection_dim):
    super(PatchEncoder,self).__init__()
    self.num_patches = num_patches
    self.projection = layers.Dense(units=projection_dim)
    self.position_embedding = layers.Embedding(
        input_dim = num_patches,
        output_dim = projection_dim
    )
  def call(self,patch):
    positions = tf.range(start=0,limit=self.num_patches,delta=1)
    encoded = self.projection(patch) + self.position_embedding(positions)
    return encoded

def create_vit_classifier():
  inputs = layers.Input(shape=input_shape)
  # Augment Layer
  augmented = data_augmentation(inputs)
  # Create Patch
  patches = Patches(patch_size)(augmented)
  # Encode patches
  encoded_patches = PatchEncoder(num_patches,projection_dim)(patches)

  # Create multiple layers of the transformer block
  for _ in range(transformer_layers):
    # layer normalization 1
    x1 = layers.LayerNormalization(epsilon=1e-6)(encoded_patches)
    # create multi-head attention layer
    attention_output = layers.MultiHeadAttention(
        num_heads=num_heads,key_dim=projection_dim,dropout=0.1
    )(x1,x1)
    # skip connection 1
    x2 = layers.Add()([attention_output,encoded_patches])
    # Layer normalization 2
    x3 = layers.LayerNormalization(epsilon=1e-6)(x2)
    # MLP
    x3 = mlp(x3,hidden_units=transformer_units,dropout_rate=0.1)
    # Skip connection 2
    encoded_patches = layers.Add()([x3,x2])

  # Create a [batch_size,projection_dim] tensor
  representation = layers.LayerNormalization(epsilon=1e-6)(encoded_patches)
  representation = layers.Flatten()(representation)
  representation = layers.Dropout(0.5)(representation)

  # Add MLP
  features = mlp(representation,hidden_units=mlp_head_units,dropout_rate=0.5)
  # classify outputs
  logits = layers.Dense(num_classes)(features)
  # Create keras model
  model = keras.Model(inputs=inputs,outputs=logits)
  return model

def run_experiment(model):
  optimizer = tfa.optimizers.AdamW(
      learning_rate=learning_rate,
      weight_decay=weight_decay
  )

  model.compile(
      optimizer=optimizer,
      loss=keras.losses.SparseCategoricalCrossentropy(from_logits=True),
      metrics=[
          keras.metrics.SparseCategoricalAccuracy(name="accuracy"),
          keras.metrics.SparseTopKCategoricalAccuracy(5,name="top_5_accuracy")
      ]
  )

  checkpoint_filepath = "./tmp/checkpoint"
  checkpoint_callback = keras.callbacks.ModelCheckpoint(
      checkpoint_filepath,
      monitor="val_accuracy",
      save_best_only=True,
      save_weights_only=True
  )

  history = model.fit(
      x=x_train,
      y=y_train,
      batch_size=batch_size,
      epochs=num_epochs,
      validation_split=0.1,
      callbacks=[checkpoint_callback]
  )

  model.load_weights(checkpoint_filepath)
  _,accuracy,top_5_accuracy = model.evaluate(x_test,y_test)
  print(f"Test accuracy: {round(accuracy*100,2)}%")
  print(f"Test Top 5 accuracy: {round(top_5_accuracy*100,2)}%")

vit_classifier = create_vit_classifier()
history = run_experiment(vit_classifier)

class_names = [
    'airplanes',
    'automobile',
    'bird',
    'cat',
    'deer',
    'dog',
    'frog',
    'horse',
    'ship',
    'truck'
]

def img_predict(images,model):
  if len(images.shape) == 3:
    out = model.predict(images.reshape(-1,*images.shape))
  else:
    out = model.predict(images)
  prediction = np.argmax(out,axis = 1)
  img_prediction = [class_names[i] for i in prediction]
  return img_prediction

index = 1000
plt.imshow(x_test[index])
prediction = img_predict(x_test[index],vit_classifier)
print(prediction)
